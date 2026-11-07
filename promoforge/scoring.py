"""Ten explainable scoring dimensions (rules-only / heuristic), taken from an editor's promo checklist.

hook, cliffhanger (looks at what comes right after the cut), coherence, standalone clarity, emotion, curiosity,
escalation (rising tension + twist), appeal (angles, stakes, relationships), spoiler control, length fit.
The weights (config.WEIGHTS) are editorial assumptions, NOT validated against real editor choices.

Show-level end-sting shrinking (lesson learned): if a show ends *every* episode with the same sting or
"cut to black", an "episode-end = cliffhanger" bonus would dominate the ranking. We measure the share of
episodes that end with such a signal and shrink all end-signal bonuses by (1 - rate).
"""
from __future__ import annotations

import re
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import lexicons as L
from .config import Config, DEFAULT, WEIGHTS
from .models import Beat, Episode, ScoreBreakdown

NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- show-level context

@dataclass
class ShowContext:
    n_episodes: int = 0
    end_signal_rate: float = 0.0     # share of episodes ending with a sting / cut-to-black
    sting_factor: float = 1.0        # multiplier applied to end-signal bonuses
    episodes_with_end_signal: list[int] = field(default_factory=list)
    known_names: set = field(default_factory=set)   # evidence-based character names (see compute_context)
    ep_pos: dict = field(default_factory=dict)      # episode number -> position in the story, 0.0 (first) .. 1.0 (last)


def _is_sentence_start(text: str, pos: int) -> bool:
    before = text[:pos].rstrip()
    return not before or before[-1] in ".!?\u2026\"\u201c\u2014-:"


def _collect_names(episodes: list[Episode]) -> set:
    """A capitalised word counts as a name only if it shows up capitalised MID-sentence somewhere in the show,
    or is a speaker label. This avoids treating sentence openers like 'Arrest' or 'Listen' as people."""
    names: set = set()
    for ep in episodes:
        for b in ep.beats():
            if b.kind == "camera":
                continue
            if b.speaker:
                names.update(x.lower() for x in re.split(r"\W+", b.speaker) if len(x) > 2)
            for m in NAME_RE.finditer(b.text or ""):
                w = m.group(0).lower()
                if w in L.COMMON_CAPS or w.endswith("ly"):
                    continue
                if not _is_sentence_start(b.text, m.start()):
                    names.add(w)
    return names - L.COMMON_CAPS


def compute_context(episodes: list[Episode], cfg: Config = DEFAULT) -> ShowContext:
    flagged = []
    for ep in episodes:
        tail = [b for b in ep.beats() if b.end >= ep.duration - 8.0]
        has = any((b.kind == "sound" and L.STING.search(b.text)) or
                  (b.kind in ("camera", "action") and re.search(r"cut to black|fade to black|smash cut", b.text, re.I))
                  for b in tail)
        if has:
            flagged.append(ep.number)
    n = max(1, len(episodes))
    rate = len(flagged) / n
    nums = sorted(e.number for e in episodes)
    ep_pos = {num: (i / (len(nums) - 1) if len(nums) > 1 else 0.0) for i, num in enumerate(nums)}
    return ShowContext(ep_pos=ep_pos, n_episodes=len(episodes), end_signal_rate=rate,
                       sting_factor=max(cfg.min_sting_factor, 1.0 - rate), episodes_with_end_signal=flagged,
                       known_names=_collect_names(episodes))


# ---------------------------------------------------------------- per-beat cues

def beat_cues(b: Beat) -> dict:
    t = b.text or ""
    s = t.strip()
    return {
        "question": s.endswith("?"),
        "exclaim": "!" in s,
        "ellipsis": s.endswith(("...", "…", "—", "--", "-")),
        "shock": L.count(L.SHOCK, t),
        "reveal": L.count(L.REVEAL, t),
        "threat": L.count(L.THREAT, t),
        "confront": L.count(L.CONFRONT, t),
        "violent": bool(L.VIOLENT_ACTION.search(t)) if b.kind == "action" else False,
        "arrival": bool(L.ARRIVAL_DISCOVERY.search(t)) if b.kind in ("action", "camera") else False,
        "sting": bool(L.STING.search(t)) if b.kind == "sound" else False,
        "closure": bool(L.CLOSURE.search(t)),
        "stakes": L.count(L.STAKES, t) if b.kind in ("dialogue", "action") else 0,
        "relation": L.count(L.RELATION, t) if b.kind in ("dialogue", "action") else 0,
        "emo_label": bool(b.emotion and L.EMOTION_WORDS.search(b.emotion)),
        "words": len(s.split()),
    }


def hook_strength(b: Beat, c: dict) -> float:
    if b.kind == "dialogue":
        s = 0.20
        if c["exclaim"]:
            s += 0.15
        if c["question"]:
            s += 0.12
        hits = c["shock"] + 1.5 * c["reveal"] + 1.5 * c["threat"] + c["confront"]
        s += min(0.40, 0.15 * hits)
        if c["words"] <= 6:
            s += 0.08
        if re.search(r"\byou\b", b.text, re.I) and (c["exclaim"] or c["question"]):
            s += 0.08
        if c["emo_label"]:
            s += 0.10
        if c["stakes"]:
            s += 0.08
        return clamp(s)
    if b.kind == "action":
        s = 0.15 + (0.35 if c["violent"] else 0.0) + (0.20 if c["arrival"] else 0.0)
        s += 0.10 * bool(L.EMOTION_WORDS.search(b.text))
        return clamp(s)
    if b.kind == "sound":
        return 0.30 if c["sting"] else 0.10
    return 0.0


def cliff_strength(b: Beat, c: dict, ctx: ShowContext) -> float:
    if b.kind == "dialogue":
        s = 0.15
        if c["question"]:
            s += 0.25
        if c["ellipsis"]:
            s += 0.22
        if c["exclaim"]:
            s += 0.08
        hits = c["shock"] + 1.5 * c["reveal"] + 1.5 * c["threat"]
        s += min(0.40, 0.15 * hits)
        if c["stakes"]:
            s += 0.10                      # a deadline / something at risk left hanging
        if c["closure"]:
            s -= 0.35
        return clamp(s)
    if b.kind == "action":
        s = 0.15 + (0.30 if c["arrival"] else 0.0) + (0.25 if c["violent"] else 0.0)
        if c["closure"]:
            s -= 0.2
        return clamp(s)
    if b.kind == "sound":
        return clamp(0.25 * ctx.sting_factor) if c["sting"] else 0.0
    return 0.0


def emotion_strength(b: Beat, c: dict) -> float:
    if b.kind == "camera":
        return 0.0
    s = 0.10
    if c["emo_label"]:
        s += 0.30
    if L.EMOTION_WORDS.search(b.text or ""):
        s += 0.15
    if c["exclaim"]:
        s += 0.10
    s += min(0.25, 0.08 * (c["shock"] + c["threat"] + c["reveal"]))
    if c["violent"]:
        s += 0.20
    return clamp(s)


# ---------------------------------------------------------------- per-episode feature store

class EpisodeFeatures:
    """Everything that can be computed once per beat. Stored on the Episode object itself."""

    def __init__(self, ep: Episode, ctx: ShowContext):
        self.ep = ep
        self.beats = ep.beats()
        self.starts = [b.start for b in self.beats]
        self.cues = [beat_cues(b) for b in self.beats]
        self.hook = [hook_strength(b, c) for b, c in zip(self.beats, self.cues)]
        self.cliff = [cliff_strength(b, c, ctx) for b, c in zip(self.beats, self.cues)]
        self.emo = [emotion_strength(b, c) for b, c in zip(self.beats, self.cues)]
        self.inten = [0.5 * h + 0.3 * e + 0.2 * k for h, e, k in zip(self.hook, self.emo, self.cliff)]
        self.tagcount: list[Counter] = []
        self.names: list[set] = []
        self.intro: list[set] = []
        for b in self.beats:
            tc: Counter = Counter()
            if b.kind in ("dialogue", "action"):
                for tag, pat in L.ANGLES.items():
                    n = len(pat.findall(b.text))
                    if n:
                        tc[tag] = n
            self.tagcount.append(tc)
            names, intro = set(), set()
            if b.kind == "dialogue":
                for m in NAME_RE.finditer(b.text):
                    w = m.group(0).lower()
                    if w in L.COMMON_CAPS or w not in ctx.known_names:
                        continue
                    names.add(w)
                if b.speaker:
                    intro.update(x.lower() for x in re.split(r"\W+", b.speaker) if x)
            else:
                for m in NAME_RE.finditer(b.text):
                    intro.add(m.group(0).lower())
            self.names.append(names)
            self.intro.append(intro)

    def idx(self, start: float, end: float, eps: float) -> tuple[int, int]:
        return bisect_left(self.starts, start - eps), bisect_left(self.starts, end - eps)


def get_features(ep: Episode, ctx: ShowContext) -> EpisodeFeatures:
    f = ep._features
    if f is None or f.__dict__.get("_ctx_key") != (ctx.sting_factor, ctx.n_episodes):
        f = EpisodeFeatures(ep, ctx)
        f._ctx_key = (ctx.sting_factor, ctx.n_episodes)
        ep._features = f
    return f


# ---------------------------------------------------------------- scoring one candidate

@dataclass
class Scored:
    scores: ScoreBreakdown
    tags: list[str]
    risks: list[str]
    hook_beat: Optional[Beat]
    cliff_beat: Optional[Beat]
    confidence: str
    n_dialogue: int
    speakers: list[str]
    text: str                  # concatenated dialogue + action text (for duplicate detection)
    tension_note: str = ""     # plain words: how the tension moves inside the clip
    cut_note: str = ""         # plain words: editing tip about where the clip ends


def _duration_fit(d: float, cfg: Config) -> float:
    if 30 <= d <= 50:
        return 1.0
    if cfg.min_dur <= d < 30:
        return 0.55 + 0.45 * (d - cfg.min_dur) / (30 - cfg.min_dur)
    if 50 < d <= cfg.max_dur:
        return 1.0 - 0.3 * (d - 50) / (cfg.max_dur - 50)
    return 0.0


def total_score(sb: ScoreBreakdown) -> float:
    return sum(getattr(sb, k) * w for k, w in WEIGHTS.items())


def score_segments(segs: list[tuple[int, float, float]], eps_map: dict[int, Episode], ctx: ShowContext,
                   cfg: Config = DEFAULT, joint_kinds: Optional[list[str]] = None) -> Optional[Scored]:
    """segs = [(episode_number, start, end), ...] in story order. Returns None if the window has no speech."""
    feats = [get_features(eps_map[e], ctx) for e, _, _ in segs]
    slices = []
    for (e, s, t), f in zip(segs, feats):
        i0, i1 = f.idx(s, t, cfg.eps)
        slices.append((f, i0, i1, s, t))
    dur = sum(t - s for _, s, t in segs)

    # collect non-camera beats per segment
    nc_per_seg = []
    for f, i0, i1, s, t in slices:
        nc_per_seg.append([i for i in range(i0, i1) if f.beats[i].kind != "camera"])
    all_nc = [(f, i) for (f, i0, i1, s, t), nc in zip(slices, nc_per_seg) for i in nc]
    dlg = [(f, i) for f, i in all_nc if f.beats[i].kind == "dialogue"]
    if len(dlg) < cfg.min_dialogue_beats:
        return None

    # ---- hook: first 3 seconds of the clip
    f0, i0, i1, s0, t0 = slices[0]
    hook_best, hook_i = 0.10, None
    for i in nc_per_seg[0]:
        b = f0.beats[i]
        dt = b.start - s0
        if dt >= cfg.hook_window:
            break
        h = f0.hook[i] * (1.0 if dt <= 1.5 else 0.85)
        if h > hook_best:
            hook_best, hook_i = h, i
    hook_beat = f0.beats[hook_i] if hook_i is not None else None

    # ---- cliffhanger: how unresolved and how tense is the moment where the clip is cut?
    #   cue        strongest "unresolved" cue among the last 3 beats (question, interrupted line, threat, reveal, arrival...)
    #   tail_int   how intense the last 2 beats are (a cut at a peak of tension is a cliffhanger)
    #   author     the script itself marks a cliffhanger/freeze at the end (shrunk by the show-level end-signal rate)
    fl, j0, j1, sl, tl = slices[-1]
    tail = nc_per_seg[-1][-3:]
    cue, cue_i = 0.0, None
    for rank, i in enumerate(reversed(tail)):
        w = (1.0, 0.75, 0.55)[rank]
        v = fl.cliff[i] * w
        if v > cue:
            cue, cue_i = v, i
    last2 = nc_per_seg[-1][-2:]
    tail_int = sum(fl.hook[i] for i in last2) / max(1, len(last2))
    author = any(L.AUTHOR_CLIFF.search(fl.beats[i].text) for i in range(j0, j1)
                 if fl.beats[i].start >= tl - 4.0 and fl.beats[i].kind != "dialogue")
    cliff = 1.15 * cue + 0.30 * tail_int
    if author:
        cliff += 0.20 * ctx.sting_factor
    if tl >= fl.ep.duration - 0.5:
        cliff += 0.06 * ctx.sting_factor
    # what comes right AFTER the cut (not in the clip): is the question still open, or is the strongest moment cut off?
    after: list[int] = []
    k = j1
    while k < len(fl.beats) and fl.beats[k].start < tl + cfg.lookahead_s and len(after) < cfg.lookahead_beats:
        if fl.beats[k].kind != "camera":
            after.append(k)
        k += 1
    cut_note = ""
    cut_too_early = False
    if after:
        peak_after = max(max(fl.hook[i], fl.cliff[i]) for i in after)
        if cue >= 0.4:
            cliff += 0.06                                   # the open question is really withheld
            first_after = fl.beats[after[0]]
            if tail and first_after.kind == "dialogue" and fl.beats[tail[-1]].kind == "dialogue" and \
                    first_after.speaker != fl.beats[tail[-1]].speaker:
                cut_note = "Cut before the answer: the reply comes right after this clip."
            else:
                cut_note = "Cut here: the moment is left unresolved."
        elif peak_after >= 0.65:
            cliff -= 0.10                                   # the clip stops just before a stronger moment
            cut_too_early = True
            cut_note = "Consider ending a little later: a stronger moment comes right after the cut."
    elif tl >= fl.ep.duration - 0.5 and cue >= 0.4:
        cut_note = "Ends where the episode ends, so the question carries into the next episode."
    cliff = clamp(cliff)
    cliff_beat = fl.beats[cue_i] if cue_i is not None else None
    # prefer showing a dialogue/action line as "the cliffhanger"
    for i in reversed(tail):
        if fl.beats[i].kind in ("dialogue", "action"):
            cliff_beat = fl.beats[i] if cue_i is None or fl.cliff[i] >= 0.8 * fl.cliff[cue_i] else cliff_beat
            break

    # ---- emotion
    em = sorted((f.emo[i] for f, i in all_nc), reverse=True)
    emotion = clamp(0.6 * (em[0] if em else 0) + 0.4 * (sum(em[:3]) / max(1, len(em[:3]))))

    # ---- appeal: angles, density of strong lines, back-and-forth, quotable line, STAKES and RELATIONSHIPS
    tags = Counter()
    for f, i in all_nc:
        tags.update(f.tagcount[i])
    strong = sum(1 for f, i in all_nc if f.hook[i] >= 0.5)
    density = strong / max(1.0, dur / 10.0)
    speakers_seq = [f.beats[i].speaker for f, i in dlg]
    turns = sum(1 for a, b in zip(speakers_seq, speakers_seq[1:]) if a != b)
    quotable = any(len(f.beats[i].text.split()) <= 7 and ("!" in f.beats[i].text or "?" in f.beats[i].text) for f, i in dlg)
    stakes_hits = sum(f.cues[i]["stakes"] for f, i in all_nc)
    rel_hits = sum(f.cues[i]["relation"] for f, i in all_nc)
    conflict_present = any(f.hook[i] >= 0.4 for f, i in all_nc)
    stakes = min(1.0, stakes_hits / 2.0)
    relationship = min(1.0, rel_hits / 2.0) * (1.0 if conflict_present else 0.5)
    appeal = clamp(0.20 * min(1, len(tags) / 2) + 0.25 * min(1, density / 1.2) + 0.15 * min(1, turns / 4)
                   + 0.10 * (1 if quotable else 0) + 0.15 * stakes + 0.15 * relationship)

    # ---- curiosity: open questions, mystery cues, an unresolved ending, a sudden arrival
    n_q = sum(1 for f, i in dlg if f.cues[i]["question"])
    mystery = sum(f.tagcount[i].get("reveal", 0) + f.tagcount[i].get("suspense", 0) for f, i in all_nc) > 0
    any_arrival = any(f.cues[i]["arrival"] for f, i in all_nc)
    curiosity = clamp(0.12 + 0.12 * min(3, n_q) + 0.15 * (1 if mystery else 0) + 0.22 * (1 if cue >= 0.5 else 0)
                      + 0.12 * (1 if any_arrival else 0))

    # ---- escalation: does the tension rise inside the clip? any new development, a late peak, a twist, no repetition
    inten = [f.inten[i] for f, i in all_nc]
    n_i = len(inten)
    if n_i >= 3:
        w = max(1, n_i // 3)
        rise = sum(inten[-w:]) / w - sum(inten[:w]) / w
    elif n_i == 2:
        rise = inten[1] - inten[0]
    else:
        rise = 0.0
    steps = min(3, sum(1 for a, b in zip(inten, inten[1:]) if b - a >= 0.18))
    peak_late = n_i > 1 and (inten.index(max(inten)) / (n_i - 1)) >= 0.5
    half = n_i // 2
    twist = any(f.cues[i]["reveal"] or f.cues[i]["arrival"] for f, i in all_nc[half:]) if n_i >= 2 else False
    rep_pen = 0.0
    prev_tok = None
    for f, i in dlg:
        tok = set(re.findall(r"[a-z']{3,}", f.beats[i].text.lower()))
        if prev_tok and tok and len(tok & prev_tok) / len(tok | prev_tok) > 0.6:
            rep_pen += 0.10
        prev_tok = tok
    escalation = clamp(0.30 + 1.1 * max(rise, -0.3) + 0.12 * steps + 0.15 * (1 if peak_late else 0)
                       + 0.10 * (1 if twist else 0) - min(0.2, rep_pen))
    if escalation >= 0.65:
        tension_note = "Tension rises through the clip"
    elif escalation <= 0.35:
        tension_note = "Tension stays flat"
    else:
        tension_note = ""

    # ---- spoiler control: does the clip show the problem being solved, or a late-story reveal?
    pos = max((ctx.ep_pos.get(e, 0.0) for e, _, _ in segs), default=0.0)
    closure_hits = sum(1 for f, i in all_nc if f.cues[i]["closure"])
    reveal_hits = sum(f.cues[i]["reveal"] for f, i in all_nc)
    strong_reveal = reveal_hits >= 2 or (reveal_hits >= 1 and any_arrival)
    spoiler = 1.0
    spoil_risks: list[str] = []
    if closure_hits >= 2:
        spoiler -= 0.25
        spoil_risks.append("shows the problem being resolved, which may give away the outcome")
    if closure_hits >= 1 and pos >= 0.9:
        spoiler -= 0.20
        spoil_risks.append("near the end of the story and wraps something up: may spoil the finale")
    if strong_reveal and pos >= 0.5:
        spoiler -= 0.15 if pos < 0.8 else 0.30
        spoil_risks.append(f"late in the story (episode {max(e for e, _, _ in segs)}): the reveal here may give away a major secret")
    if tail and fl.beats[tail[-1]].kind == "dialogue" and fl.cues[tail[-1]]["closure"]:
        spoiler -= 0.15
    spoiler = clamp(spoiler)

    # ---- coherence
    coh = 1.0
    for (f, i0_, i1_, s, t), nc in zip(slices, nc_per_seg):
        scenes = sorted({f.beats[i].scene for i in range(i0_, i1_)})
        for k, sc in enumerate(scenes[1:], 1):
            scobj = f.ep.scene(sc)
            coh -= 0.03 if (scobj and scobj.continuous) else 0.08
        # dead air
        prev_end = s
        gap = 0.0
        for i in nc:
            gap = max(gap, f.beats[i].start - prev_end)
            prev_end = max(prev_end, f.beats[i].end)
        gap = max(gap, t - prev_end)
        if gap > 6.0:
            coh -= 0.15
    joints = joint_kinds or ["stitched"] * (len(segs) - 1)
    for jk in joints:
        coh -= 0.10 if jk == "cross_direct" else (0.20 if jk == "cross" else 0.15)
    spk = {x for x in speakers_seq if x}
    if len(spk) > 4:
        coh -= 0.10
    words = sum(len(f.beats[i].text.split()) for f, i in dlg)
    if words / max(1.0, dur) < 0.5:
        coh -= 0.15
    coherence = clamp(coh)

    # ---- standalone (also builds the plain-words risk list)
    risks: list[str] = []
    sa = 1.0
    first_nc = f0.beats[nc_per_seg[0][0]] if nc_per_seg[0] else None
    first_dlg = next((f0.beats[i] for i in nc_per_seg[0] if f0.beats[i].kind == "dialogue"), None)
    if first_dlg is not None:
        fw = re.findall(r"[A-Za-z']+", first_dlg.text.lower())[:1]
        if fw and fw[0] in L.STOP_OPENERS:
            sa -= 0.12
            risks.append(f"opens on a line that leans on earlier context (\"{fw[0]} ...\")")
        if len(first_dlg.text.split()) <= 2:
            sa -= 0.10
            risks.append("opens on a very short reply whose question is not in the clip")
    if any(L.BACKREF.search(f.beats[i].text) for f, i in dlg[:3]):
        sa -= 0.10
        risks.append("early lines refer back to earlier events (\"as before\", \"again\"...)")
    sc0 = f0.ep.scene(f0.beats[nc_per_seg[0][0]].scene) if nc_per_seg[0] else None
    if sc0 is not None and s0 > sc0.start + 1.0:
        mid = 0.06 + (0.04 if sc0.continuous else 0.0)
        sa -= mid * 0.7
        risks.append("starts mid-scene without the setup shot" + (" (scene heading says CONTINUOUS)" if sc0.continuous else ""))
    mentioned, shown = set(), set()
    for f, i in all_nc:
        mentioned |= f.names[i]
        shown |= f.intro[i]
    unintro = sorted(mentioned - shown)
    if unintro:
        sa -= min(0.28, 0.07 * len(unintro))
        risks.append("names mentioned but never shown or speaking in the clip: " + ", ".join(unintro[:4]))
    if len(spk) >= 5:
        sa -= 0.10
        risks.append(f"{len(spk)} different speakers may confuse a new viewer")
    if len(segs) > 1:
        sa -= 0.08 * (len(segs) - 1)
        risks.append("joins separate moments; viewer must follow the jump")
    if any(ff.ep.timing_estimated for ff in feats):
        risks.append("timing in the source is estimated (no timestamps)")
    standalone = clamp(sa)
    risks.extend(spoil_risks)
    if cut_too_early:
        risks.append("the strongest moment comes just after the cut")

    sb = ScoreBreakdown(hook=round(clamp(hook_best), 3), cliffhanger=round(cliff, 3), standalone=round(standalone, 3),
                        emotion=round(emotion, 3), coherence=round(coherence, 3), appeal=round(appeal, 3),
                        curiosity=round(curiosity, 3), escalation=round(escalation, 3), spoiler=round(spoiler, 3),
                        duration_fit=round(_duration_fit(dur, cfg), 3))
    sb.total = round(total_score(sb), 4)

    est = any(f.ep.timing_estimated for f in feats)
    if est or sb.hook < 0.3 or sb.cliffhanger < 0.3 or sb.standalone < 0.6:
        conf = "low"
    elif sb.hook >= 0.60 and sb.cliffhanger >= 0.65 and sb.standalone >= 0.80 and sb.coherence >= 0.60 and len(risks) <= 1:
        conf = "high"
    else:
        conf = "medium"
    ordered = [t for t, _ in tags.most_common(3)] or ["drama"]
    text = " ".join(f.beats[i].text for f, i in all_nc)
    return Scored(scores=sb, tags=ordered, risks=risks, hook_beat=hook_beat, cliff_beat=cliff_beat,
                  confidence=conf, n_dialogue=len(dlg), speakers=sorted(spk), text=text,
                  tension_note=tension_note, cut_note=cut_note)


# ---------------------------------------------------------------- plain-words descriptions

def describe_beat(b: Optional[Beat], limit: int = 140) -> str:
    if b is None:
        return ""
    t = b.text if len(b.text) <= limit else b.text[: limit - 3].rstrip() + "..."
    if b.kind == "dialogue":
        return f'{b.speaker or "Voice"}: "{t}"'
    if b.kind == "sound":
        return f"[sound] {t}"
    return f"[action] {t}"


def hook_reason(b: Optional[Beat]) -> str:
    if b is None:
        return "no strong opening beat in the first 3 seconds"
    c = beat_cues(b)
    bits = []
    if c["violent"]:
        bits.append("a physical shock")
    if c["reveal"]:
        bits.append("a reveal")
    if c["threat"]:
        bits.append("a threat")
    if c["confront"]:
        bits.append("a confrontation")
    if c["question"]:
        bits.append("a direct question")
    if c["exclaim"] and not bits:
        bits.append("a charged outburst")
    return "opens on " + (", ".join(bits[:2]) if bits else "a spoken line") + " within 3 seconds"


def cliff_reason(b: Optional[Beat]) -> str:
    if b is None:
        return "no clear unresolved ending"
    c = beat_cues(b)
    if c["question"]:
        return "ends on an unanswered question"
    if c["ellipsis"]:
        return "ends on an interrupted or trailing line"
    if c["threat"]:
        return "ends on a threat"
    if c["reveal"]:
        return "ends on a reveal with no reaction yet"
    if c["arrival"]:
        return "ends on a sudden arrival or discovery"
    if c["violent"]:
        return "ends on a physical shock"
    if c["sting"]:
        return "ends on a sound sting"
    return "ends mid-conflict"
