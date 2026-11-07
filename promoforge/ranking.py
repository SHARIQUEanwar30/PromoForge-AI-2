"""Diversity-aware ranking (greedy MMR) with near-duplicate removal and plain-English rank reasons."""
from __future__ import annotations

import re

from .candidate_generator import Candidate, overlap
from .config import Config, DEFAULT, WEIGHTS
from .models import Beat, Episode, Promo, ScoreBreakdown, Segment, ValidationReport
from .scoring import ShowContext, cliff_reason, describe_beat, get_features, hook_reason
from .validator import validate_promo

_WORD = re.compile(r"[a-z']{4,}")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def time_overlap_ratio(a: Candidate, b: Candidate) -> float:
    best = 0.0
    for ea, sa, ta in a.segs:
        for eb, sb, tb in b.segs:
            if ea == eb:
                best = max(best, overlap((sa, ta), (sb, tb)) / max(1e-6, min(ta - sa, tb - sb)))
    return best


def mmr_select(cands: list[Candidate], n: int, cfg: Config = DEFAULT) -> list[Candidate]:
    """Greedy: pick the best remaining candidate after penalising repeats of episode, angle and wording."""
    pool = sorted(cands, key=lambda c: c.composite, reverse=True)
    toks = {c.key: _tokens(c.scored.text) for c in pool if c.scored}
    chosen: list[Candidate] = []
    ep_count: dict[int, int] = {}
    tag_count: dict[str, int] = {}
    remaining = list(pool)
    while remaining and len(chosen) < n:
        best, best_val = None, -1e9
        for c in remaining:
            dup = any(time_overlap_ratio(c, k) > cfg.dup_overlap or
                      jaccard(toks[c.key], toks[k.key]) > cfg.dup_jaccard for k in chosen)
            if dup:
                continue
            eps_ = {e for e, _, _ in c.segs}
            if any(ep_count.get(e, 0) >= cfg.max_per_episode for e in eps_):
                continue
            pen = sum(cfg.mmr_episode_penalty * ep_count.get(e, 0) for e in eps_)
            pen += cfg.mmr_tag_penalty * tag_count.get(c.scored.tags[0], 0)
            val = c.composite - pen
            if val > best_val:
                best, best_val = c, val
        if best is None:
            break
        chosen.append(best)
        for e in {e for e, _, _ in best.segs}:
            ep_count[e] = ep_count.get(e, 0) + 1
        tag_count[best.scored.tags[0]] = tag_count.get(best.scored.tags[0], 0) + 1
        remaining = [c for c in remaining if c is not best]
    return chosen


def transcript_for(segs: list[Segment], emap: dict[int, Episode], cfg: Config = DEFAULT) -> list[dict]:
    """Rebuild the transcript from the script (never from AI text)."""
    out = []
    for s in segs:
        ep = emap[s.episode]
        f = ep._features  # may be None if features were not built; fall back to direct scan
        for b in ep.beats():
            if b.kind == "camera":
                continue
            if b.start >= s.start - cfg.eps and b.start < s.end - cfg.eps:
                out.append({"episode": s.episode, "start": round(b.start, 2), "end": round(b.end, 2),
                            "kind": b.kind, "speaker": b.speaker, "text": b.text, "beat_id": b.id})
    return out


def beat_ids_for(segs: list[Segment], emap: dict[int, Episode], cfg: Config = DEFAULT) -> None:
    for s in segs:
        s.beat_ids = [b.id for b in emap[s.episode].beats()
                      if b.start >= s.start - cfg.eps and b.start < s.end - cfg.eps]


def _top_dims(sb: ScoreBreakdown, k: int = 2) -> list[str]:
    dims = {d: getattr(sb, d) * WEIGHTS[d] for d in WEIGHTS if d not in ("duration_fit", "spoiler")}
    return [d for d, _ in sorted(dims.items(), key=lambda kv: kv[1], reverse=True)[:k]]


NICE = {"hook": "hook", "cliffhanger": "cliffhanger", "standalone": "standalone clarity", "emotion": "emotional pull",
        "coherence": "coherence", "appeal": "promo appeal", "curiosity": "curiosity", "escalation": "rising tension",
        "spoiler": "spoiler control"}


def _why_text(sc) -> str:
    """Plain-words reason: hook, how the tension moves, how it ends."""
    bits = [f"Hook: {hook_reason(sc.hook_beat)}."]
    if sc.tension_note:
        bits.append(sc.tension_note + ".")
    bits.append(f"Cliffhanger: {cliff_reason(sc.cliff_beat)}.")
    return " ".join(bits)


def candidate_to_promo(c: Candidate, emap: dict[int, Episode], cfg: Config = DEFAULT) -> Promo:
    sc = c.scored
    segs = [Segment(episode=e, start=s, end=t) for e, s, t in c.segs]
    beat_ids_for(segs, emap, cfg)
    pid = "P" + "_".join(f"E{e:03d}-{int(round(s * 10)):05d}-{int(round(t * 10)):05d}" for e, s, t in c.segs)
    p = Promo(
        promo_id=pid, kind=c.kind, segments=segs,
        hook=describe_beat(sc.hook_beat), cliffhanger=describe_beat(sc.cliff_beat),
        why=_why_text(sc),
        cut_note=sc.cut_note,
        scores=sc.scores.model_copy(), heuristic_scores=sc.scores.model_copy(), scoring_mode="heuristic",
        confidence=sc.confidence, standalone_risks=list(sc.risks), tags=list(sc.tags),
        transcript=transcript_for(segs, emap, cfg),
    )
    p.validation = validate_promo(p, emap, cfg)
    return p


def finalize_ranking(promos: list[Promo]) -> None:
    """Assign ranks and plain-English reasons (in place)."""
    for i, p in enumerate(promos, 1):
        p.rank = i
        top = _top_dims(p.scores)
        strengths = " and ".join(f"{NICE[d]} ({getattr(p.scores, d):.2f})" for d in top)
        reason = f"Ranked #{i} (score {p.scores.total:.2f}): strongest on {strengths}; angle: {p.tags[0]}."
        if p.standalone_risks:
            reason += f" Watch out: {p.standalone_risks[0]}."
        if p.kind != "single":
            reason += " Multi-segment promo."
        p.rank_reason = reason


def mmr_select_promos(promos: list[Promo], n: int, cfg: Config = DEFAULT) -> list[Promo]:
    """Re-run the same diversity-aware selection on finished Promo objects (used after LLM judging)."""
    from types import SimpleNamespace
    adapters = []
    for p in promos:
        c = Candidate(kind=p.kind, segs=[(s.episode, s.start, s.end) for s in p.segments],
                      scored=SimpleNamespace(tags=p.tags or ["drama"], text=" ".join(t["text"] for t in p.transcript)),
                      composite=p.scores.total)
        c.promo = p  # type: ignore[attr-defined]
        adapters.append(c)
    return [c.promo for c in mmr_select(adapters, n, cfg)]  # type: ignore[attr-defined]


# ---------------------------------------------------------------- quality floor (many promos, only good ones)

def quality_floor(best_total: float, cfg: Config = DEFAULT) -> float:
    """The score a promo needs to be listed. Relative to the story's own best, so a quieter story still gets results."""
    return max(0.60, min(cfg.quality_min_total, 0.85 * best_total))


def quality_pool(cands: list[Candidate], cfg: Config = DEFAULT) -> list[Candidate]:
    """Keep only candidates that are good enough to be listed; never fewer than a small minimum."""
    scored = [c for c in cands if c.scored is not None]
    if not scored:
        return cands
    floor = quality_floor(max(c.composite for c in scored), cfg)
    good = [c for c in scored if c.composite >= floor and c.scored.scores.hook >= cfg.quality_min_hook
            and c.scored.scores.cliffhanger >= cfg.quality_min_cliff]
    if len(good) < cfg.quality_min_keep:
        good = sorted(scored, key=lambda c: c.composite, reverse=True)[: cfg.quality_min_keep * 3]
    return good


def quality_filter_promos(promos: list[Promo], cfg: Config = DEFAULT) -> list[Promo]:
    """Same rule on finished promos (after the AI step blended the scores)."""
    if not promos:
        return promos
    floor = quality_floor(max(p.scores.total for p in promos), cfg)
    good = [p for p in promos if p.scores.total >= floor and p.scores.hook >= cfg.quality_min_hook
            and p.scores.cliffhanger >= cfg.quality_min_cliff]
    if len(good) < cfg.quality_min_keep:
        good = sorted(promos, key=lambda p: p.scores.total, reverse=True)[: cfg.quality_min_keep]
        good = [p for p in promos if p in good]
    return good


# ---------------------------------------------------------------- must-pass gates

GATES = (("hook", 0.4), ("cliffhanger", 0.4), ("standalone", 0.3), ("spoiler", 0.5))
GATE_LEVEL = 0.60


def gate_penalty(sb: ScoreBreakdown) -> float:
    """An editor's must-pass checks (hook, cliffhanger, clear-alone, no spoiler) should not be hidden by a high average.
    Below 0.60 on any of them the promo loses a little rank score; the further below, the more. Spoilers weigh most."""
    return sum((GATE_LEVEL - getattr(sb, d)) * w for d, w in GATES if getattr(sb, d) < GATE_LEVEL)


def apply_gates(promos: list[Promo]) -> int:
    """Lower the ranking score of promos that fail a must-pass check; returns how many were lowered (in place)."""
    n = 0
    for p in promos:
        pen = gate_penalty(p.scores)
        if pen > 0:
            p.scores.total = round(max(0.0, p.scores.total - pen), 4)
            failed = [d for d, _ in GATES if getattr(p.scores, d) < GATE_LEVEL]
            p.notes.append(f"Ranked lower (-{pen:.2f}) because of a weak must-pass check: {', '.join(failed)}.")
            n += 1
    return n
