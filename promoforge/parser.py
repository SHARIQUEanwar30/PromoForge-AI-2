"""Four generic screenplay parsers with auto-detection.

Formats:
  labelled  - blocks like  **SPEAKER (emotion):**  then  Start: (mm:ss.xx) | End: (mm:ss.xx)  then the text
  inline    - lines like   [mm:ss - mm:ss] NAME: text
  fountain  - INT./EXT. headings, CHARACTER cues, dialogue (NO timestamps -> timing is ESTIMATED and flagged)
  prose     - plain paragraphs (NO timestamps -> timing is ESTIMATED and flagged)

Every parser returns an Episode made of Scenes made of Beats. Beat IDs are unique across a
run because they contain the episode and the scene: E021-S02-B003.

The parsers never rely on blank lines (PDF extraction loses them: "compact mode").
"""
from __future__ import annotations

import re
from typing import Optional

from .config import Config, DEFAULT
from .lexicons import NONDIALOGUE_LABELS
from .models import Beat, Episode, Scene

# ---------------------------------------------------------------- helpers

TS_RE = re.compile(r"^\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\s*$")


def parse_ts(s: str) -> float:
    s = s.strip().strip("()[] ")
    m = TS_RE.match(s)
    if m:
        h = int(m.group(1) or 0)
        return h * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return float(s)  # plain seconds


def _strip_quotes(t: str) -> str:
    t = t.strip()
    pairs = [('"', '"'), ("“", "”"), ("'", "'")]
    for a, b in pairs:
        if len(t) >= 2 and t.startswith(a) and t.endswith(b):
            return t[1:-1].strip()
    return t.strip('"“”').strip()


def _emotion_from_parens(g: str) -> str:
    """'(O.S.) (Gasping)' -> 'Gasping'. Stage tags like O.S./V.O./CONT'D are dropped."""
    parts = [p.strip() for p in re.findall(r"\(([^)]*)\)", g or "")]
    parts = [p for p in parts if p and not re.fullmatch(r"(?:V\.?O\.?|O\.?S\.?|O\.?C\.?|CONT'?D)", p, re.I)]
    return ", ".join(parts)


def _kind_for_label(label: str) -> str:
    return NONDIALOGUE_LABELS.get(label.strip().lower(), "dialogue")


def _speaker(name: str) -> str:
    return " ".join(w.capitalize() for w in re.sub(r"\s+", " ", name.strip()).split(" "))


def _bid(ep: int, scene: int, n: int) -> str:
    return f"E{ep:03d}-S{scene:02d}-B{n:03d}"


def _number_from_text(s: str) -> Optional[int]:
    m = re.search(r"(\d+)", s or "")
    return int(m.group(1)) if m else None


def number_from_filename(name: str) -> Optional[int]:
    base = name.rsplit("/", 1)[-1]
    m = re.search(r"(?:episode|ep|e)[\s_\-]*0*(\d{1,4})", base, re.I)
    if m:
        return int(m.group(1))
    m = re.match(r"\s*0*(\d{1,4})\b", base)
    return int(m.group(1)) if m else None


def is_english(text: str) -> bool:
    from .lexicons import ENGLISH_STOPWORDS
    words = re.findall(r"[A-Za-z']+", text.lower())
    if len(words) < 30:
        return True
    hits = sum(1 for w in words if w in ENGLISH_STOPWORDS)
    return hits / len(words) > 0.08


# ---------------------------------------------------------------- subtitle files (.srt / .vtt) -> inline text

CUE_TIME_RE = re.compile(
    r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")
_TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")
SUB_SPEAKER_RE = re.compile(r"^([A-Z][A-Za-z0-9 .'\-]{0,28}):\s+(\S.*)$")


def _cue_seconds(h, m, sec, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(sec) + int(ms.ljust(3, "0")[:3]) / 1000.0


def _inline_ts(t: float) -> str:
    m = int(t // 60)
    return f"{m:02d}:{t - 60 * m:05.2f}"


def subtitles_to_inline(text: str) -> tuple[str, bool]:
    """Turn SRT / WebVTT text into the inline format '[mm:ss.xx - mm:ss.xx] NAME: text' so one parser handles it.

    Returns (text, has_speaker_names). Lines like [door slams] or (music) become SOUND beats; a gap of 8 s or more starts a
    new scene. Subtitles without a 'NAME:' prefix are given the speaker 'Voice'."""
    out: list[str] = []
    named = False
    last_end = None
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    n_scene = 0
    for blk in blocks:
        lines = [l.strip() for l in blk.split("\n") if l.strip()]
        ti = next((i for i, l in enumerate(lines) if CUE_TIME_RE.match(l)), None)
        if ti is None:
            continue
        m = CUE_TIME_RE.match(lines[ti])
        a = _cue_seconds(m.group(1), m.group(2), m.group(3), m.group(4))
        b = _cue_seconds(m.group(5), m.group(6), m.group(7), m.group(8))
        body = [_TAG_RE.sub("", l).strip() for l in lines[ti + 1:]]
        body = [l for l in body if l]
        if not body:
            continue
        if last_end is None or a - last_end >= 8.0:
            n_scene += 1
            out.append(f"SCENE {n_scene}")
        last_end = max(b, a)
        parts = len(body)
        for k, l in enumerate(body):
            sa = a + (b - a) * k / parts
            sb = a + (b - a) * (k + 1) / parts
            l = re.sub(r"^[-\u2013\u2014]\s*", "", l)
            if (l.startswith("[") and l.endswith("]")) or (l.startswith("(") and l.endswith(")")):
                out.append(f"[{_inline_ts(sa)} - {_inline_ts(sb)}] SOUND: {l[1:-1].strip()}")
                continue
            sm = SUB_SPEAKER_RE.match(l)
            if sm:
                named = True
                out.append(f"[{_inline_ts(sa)} - {_inline_ts(sb)}] {sm.group(1).strip()}: {sm.group(2).strip()}")
            else:
                out.append(f"[{_inline_ts(sa)} - {_inline_ts(sb)}] Voice: {l}")
    return "\n".join(out), named


# ---------------------------------------------------------------- detection

LABEL_RE = re.compile(r"^\s*\*\*\s*([^*:()]+?)\s*((?:\([^)]*\)\s*)*):\s*\*\*\s*$")
LABEL_TIME_RE = re.compile(r"Start:\s*\(?\s*([\d:.]+)\s*\)?\s*\|\s*End:\s*\(?\s*([\d:.]+)\s*\)?", re.I)
INLINE_RE = re.compile(
    r"^\s*[\[(]\s*([\d:.]+)\s*(?:-|–|—|to)\s*([\d:.]+)\s*[\])]\s*"
    r"(?:([A-Za-z][A-Za-z0-9 .'_/\-]{0,40}?)\s*(?:\(([^)]*)\))?\s*:\s*)?(.+?)\s*$"
)
SLUG_RE = re.compile(r"^\s*(?:\d+[.)]\s*)?(INT\.?|EXT\.?|INT\./EXT\.?|I/E\.?|EST\.?)[\s/.]", re.I)
SCENE_MARK_RE = re.compile(r"^\s*(?:#+\s*)?(?:---+\s*)?SCENE\s+\d+\b", re.I)


def detect_format(text: str) -> str:
    lines = text.splitlines()
    labels = sum(1 for l in lines if LABEL_RE.match(l))
    ltimes = sum(1 for l in lines if LABEL_TIME_RE.search(l))
    if labels >= 3 and ltimes >= 3:
        return "labelled"
    inl = sum(1 for l in lines if INLINE_RE.match(l))
    if inl >= 3:
        return "inline"
    slugs = sum(1 for l in lines if SLUG_RE.match(l))
    if slugs >= 1:
        return "fountain"
    return "prose"


# ---------------------------------------------------------------- header (episode number, logline, continuity)

def _parse_header(lines: list[str]) -> dict:
    """Read EPISODE NUMBER / LOGLINE / CONTINUITY lines (any order, any format)."""
    out = {"number": None, "logline": "", "continuity": ""}
    key = None
    for raw in lines:
        l = raw.strip()
        if not l:
            continue
        low = l.lower()
        m = re.match(r"^#*\s*episode(?:\s+number)?\s*[:#]?\s*(?:episode\s*)?(\d+)\b\s*[:\-–]?\s*(.*)$", l, re.I)
        if m and out["number"] is None:
            out["number"] = int(m.group(1))
            key = None
            continue
        if low.startswith("episode logline") or low.startswith("logline") or low.startswith("summary"):
            out["logline"] = l.split(":", 1)[1].strip() if ":" in l else ""
            key = "logline"
            continue
        if low.startswith("continuity"):
            out["continuity"] = l.split(":", 1)[1].strip() if ":" in l else ""
            key = "continuity"
            continue
        if key and not (SCENE_MARK_RE.match(l) or l.startswith("---")):
            out[key] = (out[key] + " " + l).strip()
    return out


# ---------------------------------------------------------------- labelled parser

def parse_labelled(text: str, source: str = "", default_number: int = 1, cfg: Config = DEFAULT) -> Episode:
    lines = text.splitlines()
    # split header / body at SCRIPT START or first scene marker
    body_start = 0
    for i, l in enumerate(lines):
        if "SCRIPT START" in l.upper() or SCENE_MARK_RE.match(l) or l.strip().lower().startswith("scene heading"):
            body_start = i
            break
    else:
        body_start = len(lines)
    head = _parse_header(lines[:body_start])
    number = head["number"] or number_from_filename(source) or default_number

    scenes: list[Scene] = []
    cur: Optional[Scene] = None
    counters: dict[int, int] = {}
    pend_label = None  # (name, emotion)
    pend_time = None
    buf: list[str] = []
    warnings: list[str] = []

    def new_scene(idx: Optional[int] = None) -> Scene:
        nonlocal cur
        if idx is None:
            idx = (scenes[-1].index + 1) if scenes else 1
        cur = Scene(index=idx)
        scenes.append(cur)
        counters[idx] = 0
        return cur

    def flush():
        nonlocal pend_label, pend_time, buf, cur
        if pend_label and pend_time:
            if cur is None:
                new_scene(1)
            name, emo = pend_label
            kind = _kind_for_label(name)
            txt = " ".join(buf).strip()
            if kind == "dialogue":
                txt = _strip_quotes(txt)
            if txt or kind == "camera":
                counters[cur.index] += 1
                cur.beats.append(Beat(
                    id=_bid(number, cur.index, counters[cur.index]),
                    episode=number, scene=cur.index, kind=kind,
                    speaker=_speaker(name) if kind == "dialogue" else None,
                    text=txt, start=pend_time[0], end=max(pend_time[1], pend_time[0]),
                    emotion=(emo or None),
                ))
        elif pend_label and not pend_time:
            warnings.append(f"label '{pend_label[0]}' had no Start/End line; skipped")
        pend_label, pend_time, buf = None, None, []

    for raw in lines[body_start:]:
        l = raw.strip()
        if not l:
            continue
        m = SCENE_MARK_RE.match(l)
        if m:
            flush()
            idx = _number_from_text(l)
            new_scene(idx if idx and not any(s.index == idx for s in scenes) else None)
            continue
        low = l.lower()
        if low.startswith("scene heading"):
            flush()
            if cur is None or cur.heading:
                new_scene()
            cur.heading = l.split(":", 1)[1].strip() if ":" in l else l
            continue
        if low.startswith("scene start"):
            flush()
            if cur is None:
                new_scene(1)
            try:
                cur.start = parse_ts(l.split(":", 1)[1])
            except ValueError:
                pass
            continue
        if low.startswith("scene end"):
            flush()
            if cur is not None:
                try:
                    cur.end = parse_ts(l.split(":", 1)[1])
                except ValueError:
                    pass
            continue
        if low.startswith("actions and dialogue") or "script start" in low or "script end" in low:
            flush()
            continue
        lm = LABEL_RE.match(l)
        if lm:
            flush()
            pend_label = (lm.group(1), _emotion_from_parens(lm.group(2)))
            continue
        tm = LABEL_TIME_RE.search(l)
        if tm and pend_label and pend_time is None:
            try:
                pend_time = (parse_ts(tm.group(1)), parse_ts(tm.group(2)))
            except ValueError:
                warnings.append(f"bad timestamp line: {l[:60]}")
                pend_label = None
            continue
        if pend_label and pend_time:
            buf.append(l)
    flush()

    return _finish(number, head, scenes, source, "labelled", False, warnings)


# ---------------------------------------------------------------- inline parser

def parse_inline(text: str, source: str = "", default_number: int = 1, cfg: Config = DEFAULT) -> Episode:
    lines = text.splitlines()
    first_ts = next((i for i, l in enumerate(lines) if INLINE_RE.match(l)), len(lines))
    head = _parse_header([l for l in lines[:first_ts] if not SCENE_MARK_RE.match(l)])
    number = head["number"] or number_from_filename(source) or default_number
    scenes: list[Scene] = []
    cur: Optional[Scene] = None
    counters: dict[int, int] = {}
    warnings: list[str] = []

    def new_scene(heading: str = "") -> Scene:
        nonlocal cur
        idx = (scenes[-1].index + 1) if scenes else 1
        cur = Scene(index=idx, heading=heading)
        scenes.append(cur)
        counters[idx] = 0
        return cur

    for l in lines:
        s = l.strip()
        if not s:
            continue
        if SCENE_MARK_RE.match(s) or re.match(r"^\s*(?:#+\s*)?(?:---+|===+)\s*(?:scene\b.*)?$", s, re.I):
            new_scene(re.sub(r"^[#\-= ]+", "", s).strip())
            continue
        m = INLINE_RE.match(s)
        if not m:
            continue
        if cur is None:
            new_scene()
        try:
            a, b = parse_ts(m.group(1)), parse_ts(m.group(2))
        except ValueError:
            warnings.append(f"bad timestamp: {s[:60]}")
            continue
        who, emo, txt = m.group(3), (m.group(4) or "").strip(), m.group(5).strip()
        if who:
            kind = _kind_for_label(who)
            speaker = _speaker(who) if kind == "dialogue" else None
        else:
            kind, speaker = "action", None
        if kind == "dialogue":
            txt = _strip_quotes(txt)
        counters[cur.index] += 1
        cur.beats.append(Beat(
            id=_bid(number, cur.index, counters[cur.index]), episode=number, scene=cur.index,
            kind=kind, speaker=speaker, text=txt, start=a, end=max(a, b), emotion=emo or None,
        ))
    return _finish(number, head, scenes, source, "inline", False, warnings)


# ---------------------------------------------------------------- fountain parser (estimated timing)

CUE_RE = re.compile(r"^[A-Z][A-Z0-9 .'\-]{0,38}(?:\s*\((?:V\.?O\.?|O\.?S\.?|O\.?C\.?|CONT'?D)\))?\s*$")
TRANSITION_RE = re.compile(r"^(?:[A-Z ]+ TO:|FADE (?:IN|OUT)[.:]?|CUT TO BLACK\.?|THE END\.?|SMASH CUT.*|DISSOLVE.*)\s*$")


def _est_dialogue(txt: str, cfg: Config) -> float:
    return cfg.est_dialogue_pad + len(txt.split()) / cfg.est_words_per_sec


def _est_action(txt: str, cfg: Config) -> float:
    return cfg.est_action_pad + len(txt.split()) / cfg.est_action_words_per_sec


def parse_fountain(text: str, source: str = "", default_number: int = 1, cfg: Config = DEFAULT) -> Episode:
    lines = text.splitlines()
    first_slug = next((i for i, l in enumerate(lines) if SLUG_RE.match(l)), len(lines))
    head = _parse_header(lines[:first_slug])
    number = head["number"] or number_from_filename(source) or default_number
    scenes: list[Scene] = []
    cur: Optional[Scene] = None
    counters: dict[int, int] = {}
    t = 0.0
    warnings = ["No timestamps in source: timing is ESTIMATED from word counts."]

    def new_scene(heading: str) -> Scene:
        nonlocal cur
        idx = (scenes[-1].index + 1) if scenes else 1
        cur = Scene(index=idx, heading=heading, start=t)
        scenes.append(cur)
        counters[idx] = 0
        return cur

    def add(kind: str, txt: str, speaker=None, emo=None):
        nonlocal t
        if cur is None:
            new_scene("")
        dur = _est_dialogue(txt, cfg) if kind == "dialogue" else _est_action(txt, cfg)
        counters[cur.index] += 1
        cur.beats.append(Beat(
            id=_bid(number, cur.index, counters[cur.index]), episode=number, scene=cur.index, kind=kind,
            speaker=speaker, text=txt, start=round(t, 2), end=round(t + dur, 2), emotion=emo,
            timing_estimated=True,
        ))
        t += dur

    i = first_slug if first_slug < len(lines) else 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        i += 1
        if not s or s.startswith("[[") or TRANSITION_RE.match(s):
            continue
        if SLUG_RE.match(s):
            new_scene(re.sub(r"^\d+[.)]\s*", "", s))
            continue
        if CUE_RE.match(s) and not s.endswith(":") and i < n and lines[i].strip():
            speaker = _speaker(re.sub(r"\s*\(.*?\)\s*$", "", s))
            emo = None
            parts: list[str] = []
            while i < n:
                nxt = lines[i].strip()
                if not nxt or SLUG_RE.match(nxt) or (CUE_RE.match(nxt) and len(nxt.split()) <= 4 and parts):
                    break
                i += 1
                pm = re.match(r"^\((.*)\)$", nxt)
                if pm and not parts:
                    emo = pm.group(1).strip()
                    continue
                parts.append(nxt)
            if parts:
                add("dialogue", _strip_quotes(" ".join(parts)), speaker, emo)
                continue
        add("action", s)
    for sc in scenes:
        if sc.beats:
            sc.end = max(b.end for b in sc.beats)
    return _finish(number, head, scenes, source, "fountain", True, warnings)


# ---------------------------------------------------------------- prose parser (estimated timing)

QUOTE_RE = re.compile(r"[\"“]([^\"”]{2,})[\"”]")
SAID_RE = re.compile(r"[\"”],?\s*(?:said|asked|whispered|shouted|replied|cried|snapped|hissed|murmured)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")


def parse_prose(text: str, source: str = "", default_number: int = 1, cfg: Config = DEFAULT) -> Episode:
    lines = text.splitlines()
    first_body = 0
    for i, l in enumerate(lines[:6]):
        if re.match(r"^#*\s*episode\b", l.strip(), re.I) or l.strip().lower().startswith(("logline", "continuity")):
            first_body = i + 1
    head = _parse_header(lines[:first_body])
    number = head["number"] or number_from_filename(source) or default_number
    body = " ".join(l.strip() for l in lines[first_body:] if l.strip())
    sentences = re.split(r"(?<=[.!?”\"])\s+(?=[A-Z\"“])", body)
    scene = Scene(index=1, heading="")
    t, n = 0.0, 0
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        n += 1
        qm = QUOTE_RE.search(sent)
        if qm:
            who = SAID_RE.search(sent)
            txt = qm.group(1).strip()
            dur = _est_dialogue(txt, cfg)
            beat = Beat(id=_bid(number, 1, n), episode=number, scene=1, kind="dialogue",
                        speaker=who.group(1) if who else None, text=txt, start=round(t, 2),
                        end=round(t + dur, 2), timing_estimated=True)
        else:
            dur = _est_action(sent, cfg)
            beat = Beat(id=_bid(number, 1, n), episode=number, scene=1, kind="action", text=sent,
                        start=round(t, 2), end=round(t + dur, 2), timing_estimated=True)
        scene.beats.append(beat)
        t += dur
    scene.end = t
    warnings = ["Prose input: no timestamps, timing is ESTIMATED; speakers may be unknown."]
    return _finish(number, head, [scene] if scene.beats else [], source, "prose", True, warnings)


# ---------------------------------------------------------------- finishing

def _finish(number, head, scenes, source, fmt, estimated, warnings) -> Episode:
    scenes = [s for s in scenes if s.beats or s.heading]
    for s in scenes:
        if s.beats:
            lo = min(b.start for b in s.beats)
            hi = max(b.end for b in s.beats)
            if s.end <= 0 or s.end < hi:
                s.end = hi
            if s.start > lo:
                s.start = lo
    duration = max([s.end for s in scenes] + [0.0])
    ep = Episode(
        number=number, logline=head.get("logline", ""), continuity=head.get("continuity", ""),
        scenes=scenes, duration=duration, source=source, fmt=fmt, timing_estimated=estimated,
        warnings=list(warnings),
    )
    if not any(s.beats for s in scenes):
        ep.warnings.append("No beats could be parsed from this file.")
    return ep


def parse_episode(text: str, source: str = "", default_number: int = 1, fmt: Optional[str] = None,
                  cfg: Config = DEFAULT) -> Episode:
    fmt = fmt or detect_format(text)
    fn = {"labelled": parse_labelled, "inline": parse_inline, "fountain": parse_fountain, "prose": parse_prose}[fmt]
    return fn(text, source=source, default_number=default_number, cfg=cfg)
