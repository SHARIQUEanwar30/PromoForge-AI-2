"""Pipeline: ingest -> story -> candidates -> rank -> (LLM judge) -> validate -> export."""
from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .candidate_generator import Candidate, generate_candidates
from .config import Config, DEFAULT, WEIGHTS
from .evaluation import compute_metrics, failure_analysis
from .ingestion import IngestResult, load_input
from .llm_judge import judge_promos
from .llm_scan import plan_calls, scan_episodes
from .llm_provider import LLMClient, LLMError, Settings, load_settings
from .models import Episode, Promo, fmt_ts
from .ranking import (apply_gates, candidate_to_promo, finalize_ranking, mmr_select, mmr_select_promos, quality_filter_promos,
                      quality_pool)
from .scoring import compute_context, ShowContext
from .story_engine import heuristic_story, llm_story, story_context_line
from .validator import validate_promo

RULES_WARNING = ("RULES-ONLY MODE: no AI model was used. Scores are HEURISTIC (text cue lists, English only) "
                 "and are editorial assumptions, not validated predictions.")


@dataclass
class RunResult:
    promos: list[Promo]
    episodes: list[Episode]
    story: dict
    report: dict
    ctx: ShowContext
    missed: list[dict] = field(default_factory=list)
    out_dir: Optional[Path] = None


def _ai_status(llm_wanted: bool, any_llm: bool, llm_summary: Optional[dict], judge_report: Optional[dict]) -> dict:
    """What happened with the AI step, in a form the UI can turn into a friendly message.

    status: off | ok | partial | failed.   issue: None or an LLMError kind (quota, rate_limit, auth, config, ...)."""
    if not llm_wanted:
        return {"status": "off", "issue": None}
    issue = None
    if llm_summary and llm_summary.get("kind"):
        issue = llm_summary["kind"]
    elif judge_report and judge_report.get("error_kinds"):
        issue = judge_report["error_kinds"][0]
    if any_llm and issue is None:
        return {"status": "ok", "issue": None}
    return {"status": "partial" if any_llm else "failed", "issue": issue}


def run_pipeline(input_path=None, ingest: Optional[IngestResult] = None, out_dir=None, settings: Optional[Settings] = None,
                 use_llm: bool = True, top_n: Optional[int] = None, cfg: Config = DEFAULT,
                 progress: Callable[[str], None] = lambda m: None, client: Optional[LLMClient] = None) -> RunResult:
    t0 = time.time()
    settings = settings or load_settings()
    top_n = top_n or cfg.top_n
    warnings: list[str] = []

    progress("Reading and parsing the script files...")
    ing = ingest or load_input(input_path)
    episodes = ing.episodes
    if not episodes:
        raise ValueError("No episodes could be read from the input.")
    warnings += ing.warnings
    emap = {e.number: e for e in episodes}
    ctx = compute_context(episodes, cfg)

    llm_wanted = use_llm and (client is not None or settings.provider not in ("none", ""))
    story = heuristic_story(episodes, ctx)

    progress("Finding and scoring candidate clips (rules)...")
    cands, cstats = generate_candidates(episodes, ctx, cfg)
    pool_n = cfg.llm_pool if llm_wanted else top_n
    good = quality_pool(cands, cfg)                      # only candidates that are good enough to be listed
    chosen = mmr_select(good, max(pool_n, top_n if not llm_wanted else pool_n), cfg)
    promos = [candidate_to_promo(c, emap, cfg) for c in chosen]

    llm_summary = None
    judge_report = None
    scan_report = None
    plan = None
    if llm_wanted:
        try:
            client = client or LLMClient(settings)
            progress("Asking the AI model to understand the story...")
            story = llm_story(client, episodes, story)
            line = story_context_line(story)
            plan = plan_calls(client.s.max_calls, len(episodes), cfg)
            if plan["scan_calls"] > 0:
                progress("Asking the AI model to look for extra strong moments...")
                new_c, agreed, scan_report = scan_episodes(client, episodes, emap, ctx, chosen, line, plan["scan_calls"], cfg)
                warnings += scan_report["warnings"]
                agreed_set = set(agreed)
                for c, p in zip(chosen, promos):
                    if c.key in agreed_set:
                        p.source = "rules+ai_scan"
                extra = []
                for c in new_c:
                    ep_ = candidate_to_promo(c, emap, cfg)
                    ep_.source = "ai_scan"
                    extra.append(ep_)
                promos = promos + extra
            # keep the judging pool inside the call budget; the AI's own picks are kept, the weakest rule picks drop first
            capacity = max(0, plan["judge_calls"]) * cfg.llm_batch
            if capacity and len(promos) > capacity:
                ai_picks = [p for p in promos if p.source == "ai_scan"][: capacity // 2]
                keep_rules = [p for p in promos if p.source != "ai_scan"][: capacity - len(ai_picks)]
                promos = keep_rules + ai_picks
            progress(f"Asking the AI model to judge {len(promos)} candidates...")
            promos, judge_report = judge_promos(client, promos, emap, ctx, line, cfg)
            warnings += judge_report["warnings"]
            if judge_report["judged"] == 0:
                warnings.append("The AI model judged nothing; results are rules-only (heuristic).")
            llm_summary = client.summary()
            warnings += llm_summary.get("events", [])
        except LLMError as e:
            warnings.append(f"AI mode failed ({e.kind}: {e}). Falling back to rules-only (heuristic) scores.")
            llm_summary = {"error": str(e), "kind": e.kind}
    any_llm = any(p.llm_scores for p in promos)
    ai = _ai_status(llm_wanted, any_llm, llm_summary, judge_report)
    if not any_llm:
        warnings.insert(0, RULES_WARNING)

    gated = apply_gates(promos) if any_llm else 0   # AI mode: a weak must-pass check (hook / cliffhanger / clear-alone / spoiler) costs rank
    final = mmr_select_promos(promos, top_n, cfg) if (any_llm or gated) else promos[:top_n]
    final = quality_filter_promos(final, cfg)
    finalize_ranking(final)
    for p in final:
        p.validation = validate_promo(p, emap, cfg)
        if not p.validation.ok:
            warnings.append(f"{p.promo_id} failed validation: {'; '.join(p.validation.errors)}")

    missed = _missed(episodes, cands, final, cfg)
    metrics = compute_metrics(final, episodes, cfg=cfg)
    report = {
        "tool": "PromoForge AI", "version": __version__,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime_seconds": round(time.time() - t0, 1),
        "mode": "llm+heuristic" if any_llm else "rules-only (heuristic)",
        "input": {"episodes": len(episodes), "files_seen": ing.files_seen, "files_skipped": ing.files_skipped,
                  "formats": sorted({e.fmt for e in episodes}),
                  "timing_estimated": any(e.timing_estimated for e in episodes),
                  "total_beats": sum(len(e.beats()) for e in episodes)},
        "candidate_stats": cstats,
        "show_context": {"end_signal_rate": ctx.end_signal_rate, "sting_factor": ctx.sting_factor,
                         "episodes_with_end_signal": ctx.episodes_with_end_signal},
        "weights_editorial_assumption_not_validated": WEIGHTS,
        "llm": llm_summary, "judge": judge_report, "scan": scan_report, "call_plan": plan, "gated_promos": gated, "ai": ai,
        "metrics": metrics,
        "warnings": list(dict.fromkeys(warnings)),
    }
    res = RunResult(final, episodes, story, report, ctx, missed)
    if out_dir:
        export_run(res, out_dir)
        res.out_dir = Path(out_dir)
    progress("Done.")
    return res


def _missed(episodes: list[Episode], cands: list[Candidate], final: list[Promo], cfg: Config) -> list[dict]:
    have = {s.episode for p in final for s in p.segments}
    cutoff = final[-1].scores.total if final else 0.0
    best: dict[int, Candidate] = {}
    for c in cands:
        e = c.segs[0][0]
        if e not in best or c.composite > best[e].composite:
            best[e] = c
    out = []
    for ep in episodes:
        if ep.number in have or ep.number not in best:
            continue
        c = best[ep.number]
        reason = "score below the list cut-off" if c.composite < cutoff else "dropped by the diversity rules (near-duplicate or per-episode cap)"
        from .scoring import describe_beat
        out.append({"episode": ep.number, "score": c.composite, "cutoff": cutoff, "reason": reason,
                    "start": c.segs[0][1], "end": c.segs[0][2],
                    "hook": describe_beat(c.scored.hook_beat), "cliffhanger": describe_beat(c.scored.cliff_beat)})
    return sorted(out, key=lambda m: m["score"], reverse=True)


# ---------------------------------------------------------------- export

def promo_to_dict(p: Promo) -> dict:
    return {
        "rank": p.rank, "promo_id": p.promo_id, "kind": p.kind,
        "segments": [{"episode": s.episode, "start_s": round(s.start, 2), "end_s": round(s.end, 2),
                      "start_ts": fmt_ts(s.start), "end_ts": fmt_ts(s.end), "duration_s": round(s.duration, 2),
                      "beat_ids": s.beat_ids} for s in p.segments],
        "total_duration_s": round(p.duration, 2),
        "hook": p.hook, "cliffhanger": p.cliffhanger, "why_it_works": p.why, "rank_reason": p.rank_reason,
        "cut_tip": p.cut_note, "found_by": p.source,
        "scores": p.scores.model_dump(), "heuristic_scores": p.heuristic_scores.model_dump() if p.heuristic_scores else None,
        "llm_scores": p.llm_scores.model_dump() if p.llm_scores else None,
        "scoring_mode": p.scoring_mode, "confidence": p.confidence, "tags": p.tags,
        "standalone_risks": p.standalone_risks, "timestamps_valid": p.validation.ok,
        "validation": p.validation.model_dump(), "notes": p.notes, "transcript": p.transcript,
    }


CSV_COLUMNS = ["rank", "promo_id", "kind", "segments", "total_duration_s", "hook", "cliffhanger", "why_it_works",
               "rank_reason", "score_total", "hook_score", "cliffhanger_score", "standalone_score", "emotion_score",
               "coherence_score", "appeal_score", "curiosity_score", "escalation_score", "spoiler_score",
               "duration_fit_score", "scoring_mode", "confidence", "angles", "cut_tip",
               "standalone_risks", "timestamps_valid", "warnings", "transcript"]


def promo_to_row(p: Promo) -> dict:
    d = promo_to_dict(p)
    segs = " | ".join(f"E{s['episode']} {s['start_ts']}-{s['end_ts']}" for s in d["segments"])
    tr = " / ".join((f"{t['speaker']}: {t['text']}" if t["kind"] == "dialogue" else f"[{t['kind']}] {t['text']}") for t in p.transcript)
    return {"rank": p.rank, "promo_id": p.promo_id, "kind": p.kind, "segments": segs,
            "total_duration_s": d["total_duration_s"], "hook": p.hook, "cliffhanger": p.cliffhanger,
            "why_it_works": p.why, "rank_reason": p.rank_reason, "score_total": p.scores.total,
            "hook_score": p.scores.hook, "cliffhanger_score": p.scores.cliffhanger,
            "standalone_score": p.scores.standalone, "emotion_score": p.scores.emotion,
            "coherence_score": p.scores.coherence, "appeal_score": p.scores.appeal,
            "curiosity_score": p.scores.curiosity, "escalation_score": p.scores.escalation,
            "spoiler_score": p.scores.spoiler, "cut_tip": p.cut_note,
            "duration_fit_score": p.scores.duration_fit, "scoring_mode": p.scoring_mode,
            "confidence": p.confidence, "angles": ", ".join(p.tags),
            "standalone_risks": " ; ".join(p.standalone_risks), "timestamps_valid": p.validation.ok,
            "warnings": " ; ".join(p.validation.warnings + p.notes), "transcript": tr}


def episodes_to_dict(episodes: list[Episode]) -> list[dict]:
    return [e.model_dump() for e in episodes]


def export_run(res: RunResult, out_dir) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "promos.json").write_text(json.dumps(
        {"mode": res.report["mode"], "warnings": res.report["warnings"], "promos": [promo_to_dict(p) for p in res.promos]},
        indent=2, ensure_ascii=False), encoding="utf-8")
    with open(out / "promos.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for p in res.promos:
            w.writerow(promo_to_row(p))
    (out / "run_report.json").write_text(json.dumps(res.report, indent=2, ensure_ascii=False), encoding="utf-8")
    if res.episodes and res.promos:                       # one .txt per promo (same style as the input) + a ZIP of them
        from .export_text import write_promo_texts
        write_promo_texts(res.promos, {e.number: e for e in res.episodes}, out)
    (out / "story_intelligence.json").write_text(json.dumps(res.story, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "parsed_script.json").write_text(json.dumps(episodes_to_dict(res.episodes), ensure_ascii=False), encoding="utf-8")
    (out / "missed_candidates.json").write_text(json.dumps(res.missed, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(out / "review_sheet.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["rank", "promo_id", "segments", "hook", "cliffhanger", "status (approved/rejected/flagged)", "notes"])
        for p in res.promos:
            r = promo_to_row(p)
            w.writerow([p.rank, p.promo_id, r["segments"], p.hook, p.cliffhanger, "", ""])
    ctx_info = {"end_signal_rate": res.ctx.end_signal_rate, "sting_factor": res.ctx.sting_factor}
    (out / "failure_analysis_private.md").write_text(
        failure_analysis(res.promos, res.episodes, res.missed, ctx_info, redact=False), encoding="utf-8")
    (out / "failure_analysis_public_redacted.md").write_text(
        failure_analysis(res.promos, res.episodes, res.missed, ctx_info, redact=True), encoding="utf-8")
    return out


def load_run(out_dir) -> RunResult:
    """Load a finished run from disk (used by the app and `evaluate`)."""
    from .models import Episode, ScoreBreakdown, Segment, ValidationReport
    out = Path(out_dir)
    pj = json.loads((out / "promos.json").read_text(encoding="utf-8"))
    report = json.loads((out / "run_report.json").read_text(encoding="utf-8"))
    story = json.loads((out / "story_intelligence.json").read_text(encoding="utf-8")) if (out / "story_intelligence.json").exists() else {}
    eps = [Episode.model_validate(e) for e in json.loads((out / "parsed_script.json").read_text(encoding="utf-8"))] \
        if (out / "parsed_script.json").exists() else []
    promos = []
    for d in pj["promos"]:
        promos.append(Promo(
            promo_id=d["promo_id"], rank=d["rank"], kind=d["kind"],
            segments=[Segment(episode=s["episode"], start=s["start_s"], end=s["end_s"], beat_ids=s.get("beat_ids", []))
                      for s in d["segments"]],
            hook=d["hook"], cliffhanger=d["cliffhanger"], why=d["why_it_works"], rank_reason=d["rank_reason"],
            cut_note=d.get("cut_tip", ""), source=d.get("found_by", "rules"),
            scores=ScoreBreakdown(**d["scores"]),
            heuristic_scores=ScoreBreakdown(**d["heuristic_scores"]) if d.get("heuristic_scores") else None,
            llm_scores=ScoreBreakdown(**d["llm_scores"]) if d.get("llm_scores") else None,
            scoring_mode=d["scoring_mode"], confidence=d["confidence"], standalone_risks=d["standalone_risks"],
            tags=d["tags"], transcript=d["transcript"], validation=ValidationReport(**d["validation"]), notes=d.get("notes", [])))
    ctx = ShowContext(**{k: v for k, v in report.get("show_context", {}).items() if k in ("end_signal_rate", "sting_factor", "episodes_with_end_signal")})
    missed = json.loads((out / "missed_candidates.json").read_text(encoding="utf-8")) if (out / "missed_candidates.json").exists() else []
    return RunResult(promos, eps, story, report, ctx, missed, out)
