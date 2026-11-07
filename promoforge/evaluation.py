"""Honest evaluation. Nothing here is invented: metrics that need labels say NOT CALCULABLE without them.

hard_constraints   always calculable (re-checked independently from the script)
precision_at_k     only from human labels (reviews.json)
approval_rate      only from human labels
gold_recall        only if gold clips are supplied
llm_agreement      only if an LLM run exists (agreement between two scorers, NOT accuracy)
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from .config import Config, DEFAULT
from .models import Episode, Promo, fmt_ts
from .validator import validate_promo

NC = "NOT CALCULABLE (no labels)"


def hard_constraints(promos: list[Promo], emap: dict[int, Episode], cfg: Config = DEFAULT) -> dict:
    n = len(promos)
    if n == 0:
        return {"n": 0, "note": "no promos"}
    checks = Counter()
    for p in promos:
        rep = validate_promo(p, emap, cfg)
        dur = sum(s.end - s.start for s in p.segments)
        checks["duration_20_to_60s"] += cfg.min_dur - cfg.eps <= dur <= cfg.max_dur + cfg.eps
        checks["timestamps_inside_real_script_range"] += all(
            s.episode in emap and -cfg.eps <= s.start < s.end <= emap[s.episode].duration + cfg.eps for s in p.segments)
        checks["no_cut_inside_dialogue_line"] += not any("middle of a dialogue" in e for e in rep.errors)
        first = p.segments[0]
        ep = emap.get(first.episode)
        checks["something_happens_in_first_3s"] += bool(ep) and any(
            b.kind in ("dialogue", "action") and first.start - cfg.eps <= b.start < first.start + cfg.hook_window
            for b in ep.beats())
        checks["has_episode_number_and_timestamps"] += all(s.episode and s.end > s.start for s in p.segments)
        checks["python_validation_passed"] += rep.ok
    out = {k: f"{v}/{n} ({100.0 * v / n:.0f}%)" for k, v in checks.items()}
    out["n"] = n
    return out


def _status(reviews: dict, pid: str) -> Optional[str]:
    r = reviews.get(pid)
    if isinstance(r, dict):
        r = r.get("status")
    return r if r in ("approved", "rejected", "flagged") else None


def precision_at_k(promos: list[Promo], reviews: Optional[dict], ks=(5, 10, 20)) -> dict:
    if not reviews:
        return {f"precision@{k}": NC for k in ks}
    out = {}
    for k in ks:
        top = promos[:k]
        labelled = [(_status(reviews, p.promo_id)) for p in top]
        done = [s for s in labelled if s in ("approved", "rejected")]
        if len(done) < len(top):
            out[f"precision@{k}"] = f"NOT CALCULABLE ({len(top) - len(done)} of the top {k} are unlabelled)"
        else:
            out[f"precision@{k}"] = round(sum(s == "approved" for s in done) / len(done), 3)
    return out


def approval_rate(reviews: Optional[dict], promos: list[Promo]) -> object:
    if not reviews:
        return NC
    st = [_status(reviews, p.promo_id) for p in promos]
    done = [s for s in st if s in ("approved", "rejected")]
    return NC if not done else {"labelled": len(done), "approved": sum(s == "approved" for s in done),
                                "rate": round(sum(s == "approved" for s in done) / len(done), 3)}


def gold_recall(promos: list[Promo], gold: Optional[list[dict]], iou: float = 0.5) -> object:
    if not gold:
        return NC.replace("labels", "gold clips")
    hit = 0
    for g in gold:
        for p in promos:
            for s in p.segments:
                if s.episode != g["episode"]:
                    continue
                inter = max(0.0, min(s.end, g["end"]) - max(s.start, g["start"]))
                union = (s.end - s.start) + (g["end"] - g["start"]) - inter
                if union > 0 and inter / union >= iou:
                    hit += 1
                    break
            else:
                continue
            break
    return {"gold_clips": len(gold), "matched_at_iou": iou, "recall": round(hit / len(gold), 3)}


def llm_agreement(promos: list[Promo]) -> object:
    both = [p for p in promos if p.llm_scores and p.heuristic_scores]
    if len(both) < 3:
        return "NOT CALCULABLE (no LLM run)"
    gaps = [abs(p.llm_scores.total - p.heuristic_scores.total) for p in both]
    return {"promos_compared": len(both), "mean_abs_gap_in_total_score": round(sum(gaps) / len(gaps), 3),
            "note": "agreement between two scorers, NOT accuracy"}


def distribution(promos: list[Promo], episodes: list[Episode]) -> dict:
    eps = Counter(s.episode for p in promos for s in p.segments[:1])
    emap = {e.number: e for e in episodes}
    at_end = sum(1 for p in promos if p.segments[-1].end >= emap[p.segments[-1].episode].duration - 0.5)
    return {
        "promos": len(promos),
        "episodes_with_a_promo": len(eps),
        "episodes_total": len(episodes),
        "max_promos_from_one_episode": max(eps.values()) if eps else 0,
        "share_ending_at_episode_end": round(at_end / max(1, len(promos)), 3),
        "kinds": dict(Counter(p.kind for p in promos)),
        "confidence": dict(Counter(p.confidence for p in promos)),
        "main_angle": dict(Counter((p.tags or ["drama"])[0] for p in promos)),
        "scoring_mode": dict(Counter(p.scoring_mode for p in promos)),
    }


def compute_metrics(promos: list[Promo], episodes: list[Episode], reviews: Optional[dict] = None,
                    gold: Optional[list[dict]] = None, cfg: Config = DEFAULT) -> dict:
    emap = {e.number: e for e in episodes}
    m = {"hard_constraints": hard_constraints(promos, emap, cfg), "distribution": distribution(promos, episodes)}
    m.update(precision_at_k(promos, reviews))
    m["approval_rate"] = approval_rate(reviews, promos)
    m["gold_recall"] = gold_recall(promos, gold)
    m["llm_vs_rules_agreement"] = llm_agreement(promos)
    m["note"] = ("Scores are editorial heuristics (and AI judgements if an LLM ran), not validated predictions. "
                 "Precision/approval need human labels; none are invented.")
    return m


def load_json(path: str | Path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------------------------------------------------------- failure analysis

_NAME_TAIL = re.compile(r":\s.*$")


def _redact_risk(r: str) -> str:
    r = re.sub(r"\"[^\"]*\"", "\"...\"", r)
    return _NAME_TAIL.sub("", r) if "names mentioned" in r else r


def failure_analysis(promos: list[Promo], episodes: list[Episode], missed: list[dict], ctx_info: dict,
                     redact: bool = False) -> str:
    """Markdown. redact=True removes every quote, speaker name and story detail (safe for a public repo)."""
    emap = {e.number: e for e in episodes}
    L: list[str] = []
    add = L.append
    add("# Failure analysis" + (" (public, redacted)" if redact else " (PRIVATE: contains script quotes)"))
    add("")
    add("Generated automatically from the run outputs. It lists where the tool is likely to pick badly. "
        "It is not a measure of accuracy.")
    add("")
    add("## 1. Built-in limits (true for every run)")
    for t in [
        "Rules-only scoring reads TEXT cues (question marks, threat/reveal words, sound stings). It cannot see acting, music or visuals.",
        "Cue lists are English-only and generic; slang, sarcasm and non-English scripts will be misjudged.",
        "A line can look like a cliffhanger (a question, a threat) while the very next line resolves it. The tool cannot always check.",
        "Standalone clarity is estimated from names and context words in the clip; it cannot know what a new viewer already understands.",
        "Score weights are editorial assumptions and have not been validated against editor decisions.",
        "Without human labels there is no precision number. Ranking order inside a small score gap is not meaningful.",
    ]:
        add(f"- {t}")
    add("")
    add("## 2. Show-level signals")
    add(f"- Share of episodes ending with a sound sting / cut-to-black: **{ctx_info.get('end_signal_rate', 0):.0%}** "
        f"(end-signal bonuses were multiplied by {ctx_info.get('sting_factor', 1):.2f} to stop them dominating).")
    d = distribution(promos, episodes)
    add(f"- {d['promos']} promos from {d['episodes_with_a_promo']} of {d['episodes_total']} episodes; "
        f"{d['share_ending_at_episode_end']:.0%} end exactly at an episode end.")
    if len(promos) >= 5:
        gap = promos[0].scores.total - promos[-1].scores.total
        close = sum(1 for p in promos if promos[0].scores.total - p.scores.total <= 0.05)
        add(f"- Score range across the list is only {gap:.2f}; {close} promos are within 0.05 of the top score, "
            "so their relative order should be treated as a tie.")
    add("")
    add("## 3. Picks most likely to be wrong")
    weak = []
    for p in promos:
        why = []
        s = p.scores
        if p.confidence == "low":
            why.append("confidence is low")
        if s.hook < 0.45:
            why.append(f"weak hook ({s.hook:.2f})")
        if s.cliffhanger < 0.45:
            why.append(f"weak cliffhanger ({s.cliffhanger:.2f})")
        if s.standalone < 0.75:
            why.append(f"standalone risk ({s.standalone:.2f})")
        if p.llm_scores and p.heuristic_scores and abs(p.llm_scores.total - p.heuristic_scores.total) > 0.25:
            why.append("AI and rules disagree strongly")
        if why:
            weak.append((p, why))
    if not weak:
        add("No pick tripped a weakness threshold (hook<0.45, cliffhanger<0.45, standalone<0.75, low confidence, big AI/rules gap).")
    for p, why in weak[:15]:
        seg = ", ".join(f"E{x.episode} {fmt_ts(x.start)}-{fmt_ts(x.end)}" for x in p.segments)
        add(f"- **Rank {p.rank}** ({seg}): " + "; ".join(why) + ".")
        if not redact:
            add(f"  - hook: {p.hook}")
            add(f"  - cliffhanger: {p.cliffhanger}")
            for r in p.standalone_risks[:3]:
                add(f"  - risk: {r}")
        else:
            for r in p.standalone_risks[:3]:
                add(f"  - risk type: {_redact_risk(r)}")
    add("")
    add("## 4. Possible misses (best clip of episodes with no promo)")
    if not missed:
        add("Every episode has at least one promo in the list.")
    for m in missed[:15]:
        line = f"- Episode {m['episode']}: best available clip scores {m['score']:.2f} (list cut-off {m['cutoff']:.2f}); reason not picked: {m['reason']}."
        add(line)
        if not redact and m.get("hook"):
            add(f"  - would open on: {m['hook']}")
            add(f"  - would end on: {m['cliffhanger']}")
    add("")
    add("## 5. Disagreement between AI and rules")
    both = [p for p in promos if p.llm_scores and p.heuristic_scores]
    if not both:
        add("No LLM run in this output (rules-only), so nothing to compare.")
    else:
        for p in sorted(both, key=lambda p: abs(p.llm_scores.total - p.heuristic_scores.total), reverse=True)[:5]:
            add(f"- Rank {p.rank}: AI {p.llm_scores.total:.2f} vs rules {p.heuristic_scores.total:.2f}.")
    add("")
    return "\n".join(L)
