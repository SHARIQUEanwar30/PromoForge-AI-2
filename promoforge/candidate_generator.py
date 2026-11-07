"""Candidate generation: enumerate beat-aligned windows, then stitched and cross-episode candidates.

Every candidate is validated by Python before it is allowed to exist (no cut inside a dialogue line,
inside the real script range, 20-60 s in total).
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from .config import Config, DEFAULT
from .models import Episode, Segment
from .scoring import ShowContext, Scored, get_features, score_segments
from .validator import cuts_dialogue, may_join, validate_segments


@dataclass
class Candidate:
    kind: str                                   # single / stitched / cross_episode
    segs: list[tuple[int, float, float]]        # (episode, start, end)
    scored: Scored | None = None
    composite: float = 0.0
    joints: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return sum(t - s for _, s, t in self.segs)

    @property
    def key(self) -> str:
        return "|".join(f"{e}:{s:.2f}-{t:.2f}" for e, s, t in self.segs)


def cut_points(ep: Episode, cfg: Config = DEFAULT) -> tuple[list[float], list[float]]:
    """Natural cut points: shot boundaries (or every beat boundary when the source has no shots)."""
    beats = ep.beats()
    has_cam = any(b.kind == "camera" for b in beats)
    starts, ends = set(), set()
    for b in beats:
        if (b.kind == "camera") if has_cam else True:
            starts.add(round(b.start, 2))
            ends.add(round(b.end, 2))
        if b.kind == "dialogue":
            starts.add(round(b.start, 2))
            ends.add(round(b.end, 2))
    for s in ep.scenes:
        starts.add(round(s.start, 2))
        ends.add(round(s.end, 2))
    S = sorted(t for t in starts if not cuts_dialogue(ep, t, cfg) and 0 <= t <= ep.duration + cfg.eps)
    E = sorted(t for t in ends if not cuts_dialogue(ep, t, cfg) and 0 < t <= ep.duration + cfg.eps)
    return S, E


def windows(ep: Episode, min_d: float, max_d: float, cfg: Config = DEFAULT):
    S, E = cut_points(ep, cfg)
    for s in S:
        lo = bisect_left(E, s + min_d - 1e-6)
        hi = bisect_right(E, s + max_d + 1e-6)
        for e in E[lo:hi]:
            yield s, e


def overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def nms(cands: list[Candidate], thresh: float, keep: int) -> list[Candidate]:
    """Non-maximum suppression inside one episode (single-segment candidates)."""
    out: list[Candidate] = []
    for c in sorted(cands, key=lambda c: c.composite, reverse=True):
        _, s, t = c.segs[0]
        ok = True
        for k in out:
            _, ks, kt = k.segs[0]
            if overlap((s, t), (ks, kt)) / max(1e-6, min(t - s, kt - ks)) > thresh:
                ok = False
                break
        if ok:
            out.append(c)
            if len(out) >= keep:
                break
    return out


def generate_candidates(episodes: list[Episode], ctx: ShowContext, cfg: Config = DEFAULT) -> tuple[list[Candidate], dict]:
    emap = {e.number: e for e in episodes}
    stats = {"windows_enumerated": 0, "windows_scored": 0, "single_kept": 0, "stitched": 0, "cross_episode": 0,
             "rejected_by_validator": 0}
    singles: list[Candidate] = []
    quick: dict[int, list[Candidate]] = {}

    for ep in episodes:
        per_ep: list[Candidate] = []
        for s, e in windows(ep, cfg.min_dur, cfg.max_dur, cfg):
            stats["windows_enumerated"] += 1
            sc = score_segments([(ep.number, s, e)], emap, ctx, cfg)
            if sc is None:
                continue
            stats["windows_scored"] += 1
            per_ep.append(Candidate("single", [(ep.number, s, e)], sc, sc.scores.total))
        keep = nms(per_ep, cfg.nms_overlap, cfg.per_episode_keep)
        singles.extend(keep)
        stats["single_kept"] += len(keep)

    # ---- stitched (skip-gap) candidates inside one episode: strong opener + strong ending
    stitched: list[Candidate] = []
    for ep in episodes:
        hooks, cliffs = [], []
        for s, e in windows(ep, cfg.stitched_seg_min, cfg.stitched_seg_max, cfg):
            f = get_features(ep, ctx)
            i0, i1 = f.idx(s, e, cfg.eps)
            nc = [i for i in range(i0, i1) if f.beats[i].kind != "camera"]
            if not nc or sum(1 for i in nc if f.beats[i].kind == "dialogue") < 1:
                continue
            h = 0.0
            for i in nc:
                if f.beats[i].start - s >= cfg.hook_window:
                    break
                h = max(h, f.hook[i])
            c = max((f.cliff[i] * w for i, w in zip(reversed(nc[-3:]), (1.0, 0.75, 0.55))), default=0.0)
            hooks.append((h, s, e))
            cliffs.append((c, s, e))
        hooks = _top_nonoverlap(hooks, cfg.stitched_top)
        cliffs = _top_nonoverlap(cliffs, cfg.stitched_top)
        for _, hs, he in hooks:
            for _, cs, ce in cliffs:
                if cs < he + cfg.stitched_min_gap:
                    continue
                d = (he - hs) + (ce - cs)
                if not (cfg.min_dur <= d <= cfg.max_dur):
                    continue
                segs = [(ep.number, hs, he), (ep.number, cs, ce)]
                stitched.append(Candidate("stitched", segs, joints=["stitched"]))

    # ---- cross-episode bridges: end of episode n + opening of n+1 when n+1 "continues directly"
    cross: list[Candidate] = []
    for a, b in zip(episodes, episodes[1:]):
        if b.number != a.number + 1:
            continue
        joinable, assumed_join = may_join(a.number, b, episodes)
        if not joinable:
            continue
        tails, heads = [], []
        fa, fb = get_features(a, ctx), get_features(b, ctx)
        for s, e in windows(a, cfg.cross_seg_min, cfg.cross_seg_max, cfg):
            if e < a.duration - 1.0:
                continue
            i0, i1 = fa.idx(s, e, cfg.eps)
            nc = [i for i in range(i0, i1) if fa.beats[i].kind != "camera"]
            h = max((fa.hook[i] for i in nc if fa.beats[i].start - s < cfg.hook_window), default=0.0)
            if nc:
                tails.append((h, s, e))
        first_start = min((x.start for x in fb.beats), default=0.0)
        for s, e in windows(b, cfg.cross_seg_min, cfg.cross_seg_max, cfg):
            if s > first_start + 0.5:
                continue
            i0, i1 = fb.idx(s, e, cfg.eps)
            nc = [i for i in range(i0, i1) if fb.beats[i].kind != "camera"]
            c = max((fb.cliff[i] * w for i, w in zip(reversed(nc[-3:]), (1.0, 0.75, 0.55))), default=0.0)
            if nc:
                heads.append((c, s, e))
        tails = sorted(tails, reverse=True)[: cfg.cross_top]
        heads = sorted(heads, reverse=True)[: cfg.cross_top]
        for _, ts, te in tails:
            for _, hs, he in heads:
                d = (te - ts) + (he - hs)
                if cfg.min_dur <= d <= cfg.max_dur:
                    cross.append(Candidate("cross_episode", [(a.number, ts, te), (b.number, hs, he)],
                                           joints=["cross" if assumed_join else "cross_direct"]))

    extra: list[Candidate] = []
    for c in stitched + cross:
        segs = [Segment(episode=e, start=s, end=t) for e, s, t in c.segs]
        if not validate_segments(segs, emap, cfg).ok:
            stats["rejected_by_validator"] += 1
            continue
        sc = score_segments(c.segs, emap, ctx, cfg, joint_kinds=c.joints)
        if sc is None:
            continue
        c.scored, c.composite = sc, sc.scores.total
        extra.append(c)
        stats["stitched" if c.kind == "stitched" else "cross_episode"] += 1

    # keep the best few extras per episode so they cannot flood the pool
    bykey: dict[int, list[Candidate]] = {}
    for c in extra:
        bykey.setdefault(c.segs[0][0], []).append(c)
    kept_extra: list[Candidate] = []
    for k, lst in bykey.items():
        kept_extra.extend(sorted(lst, key=lambda c: c.composite, reverse=True)[:4])

    allc = []
    for c in singles:
        segs = [Segment(episode=e, start=s, end=t) for e, s, t in c.segs]
        if validate_segments(segs, emap, cfg).ok:
            allc.append(c)
        else:
            stats["rejected_by_validator"] += 1
    allc.extend(kept_extra)
    return allc, stats


def _top_nonoverlap(items: list[tuple[float, float, float]], n: int) -> list[tuple[float, float, float]]:
    out: list[tuple[float, float, float]] = []
    for v, s, e in sorted(items, reverse=True):
        if all(overlap((s, e), (os_, oe)) <= 0.3 * min(e - s, oe - os_) for _, os_, oe in out):
            out.append((v, s, e))
            if len(out) >= n:
                break
    return out
