"""Small, testable helpers behind the Editing Desk page (no Streamlit import).

An editor looks at a promo, moves its start or end a little (+ / - 0.5 second) and keeps or skips it.
Python still has the last word: every move is checked with the same rules as the engine
(20-60 seconds, inside the episode, never in the middle of a spoken line). A move that breaks a rule is refused
with a plain-words reason, and nothing changes.
"""
from __future__ import annotations

import html
from typing import Optional

from .config import Config, DEFAULT
from .models import Episode, Promo, Segment, fmt_ts
from .ranking import beat_ids_for, transcript_for
from .scoring import describe_beat
from .validator import validate_segments

STEP = 0.5          # seconds moved by one click on + or -


def clamp_time(t: float, ep: Episode) -> float:
    return round(min(max(0.0, float(t)), float(ep.duration)), 2)


def line_at(ep: Episode, t: float, cfg: Config = DEFAULT):
    """The spoken line that time t falls strictly inside (a cut there would slice the line), or None."""
    for b in ep.beats():
        if b.kind == "dialogue" and b.start + cfg.eps < t < b.end - cfg.eps:
            return b
    return None


def _short(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def check_edit(ep: Episode, emap: dict[int, Episode], start: float, end: float, cfg: Config = DEFAULT) -> tuple[bool, str]:
    """(ok, message). The message is written for an editor, in seconds (the same unit as the boxes on the page)."""
    start, end = round(float(start), 2), round(float(end), 2)
    if start < -cfg.eps or end > ep.duration + cfg.eps:
        return False, f"Not changed. That is outside the episode (it runs from 0 to {ep.duration:.1f} s)."
    if end <= start + cfg.eps:
        return False, "Not changed. The end has to come after the start."
    dur = end - start
    if dur < cfg.min_dur - cfg.eps:
        return False, (f"Not changed. That would make the clip {dur:.1f} s. "
                       f"Clips must be between {cfg.min_dur:.0f} and {cfg.max_dur:.0f} seconds.")
    if dur > cfg.max_dur + cfg.eps:
        return False, (f"Not changed. That would make the clip {dur:.1f} s. "
                       f"Clips must be between {cfg.min_dur:.0f} and {cfg.max_dur:.0f} seconds.")
    for label, t in (("start", start), ("end", end)):
        b = line_at(ep, t, cfg)
        if b is not None:
            return False, (f"Not changed. The {label} ({t:.2f} s) is inside the line “{_short(b.text)}” "
                           f"({b.start:.2f} s to {b.end:.2f} s). Try {b.start:.2f} or {b.end:.2f}.")
    rep = validate_segments([Segment(episode=ep.number, start=start, end=end)], emap, cfg)
    if not rep.ok:
        return False, "Not changed. " + rep.errors[0]
    return True, f"✔ {dur:.1f} s · inside {cfg.min_dur:.0f} to {cfg.max_dur:.0f} s · no line cut in half"


def nudge_time(ep: Episode, which: str, current: float, delta: float, cfg: Config = DEFAULT) -> tuple[float, bool]:
    """Move `current` by `delta` seconds. If that lands inside a spoken line, slide on to the edge of that line in the
    direction of the click, so the editor is never stuck. Returns (new_time, slid)."""
    t = clamp_time(current + delta, ep)
    b = line_at(ep, t, cfg)
    if b is None:
        return t, False
    return clamp_time(b.end if delta > 0 else b.start, ep), True       # same rule for the start and for the end


def apply_edit(p: Promo, emap: dict[int, Episode], start: float, end: float, cfg: Config = DEFAULT) -> Promo:
    """A copy of the promo with new times. The hook and cliffhanger are re-read from the new first and last lines."""
    if len(p.segments) != 1:
        return p
    s0 = p.segments[0]
    start, end = round(float(start), 2), round(float(end), 2)
    if abs(start - s0.start) < 0.005 and abs(end - s0.end) < 0.005:
        return p
    seg = Segment(episode=s0.episode, start=start, end=end)
    beat_ids_for([seg], emap, cfg)
    q = p.model_copy(deep=True)
    q.segments = [seg]
    q.transcript = transcript_for([seg], emap, cfg)
    inside = [b for b in emap[seg.episode].beats()
              if b.kind != "camera" and seg.start - cfg.eps <= b.start < seg.end - cfg.eps]
    if inside:
        q.hook = describe_beat(inside[0])
        q.cliffhanger = describe_beat(inside[-1])
    q.cut_note = ""
    q.validation = validate_segments([seg], emap, cfg)
    q.notes = list(p.notes) + [f"Times edited by the editor. The tool had picked {s0.start:.2f}-{s0.end:.2f} s."]
    return q


def decision_of(reviews: dict, promo_id: str) -> str:
    return (reviews.get(promo_id) or {}).get("status", "")


def effective_promos(promos: list[Promo], emap: dict[int, Episode], reviews: dict, kept_only: bool = False,
                     cfg: Config = DEFAULT) -> list[Promo]:
    """The promos as the editor left them: edited times applied, and (optionally) only the ones marked Keep."""
    out = []
    for p in promos:
        r = reviews.get(p.promo_id) or {}
        if kept_only and r.get("status") != "approved":
            continue
        e = r.get("edit")
        if e and len(p.segments) == 1:
            p = apply_edit(p, emap, e["start"], e["end"], cfg)
        out.append(p)
    return out


def script_view_html(ep: Episode, start: float, end: float, cfg: Config = DEFAULT, height: int = 420) -> str:
    """A full web page (for an iframe) with the whole episode script. Lines inside the clip are yellow, there are
    'clip starts / ends' marks, and the box opens already scrolled to the start of the clip."""
    rows = []
    inside_idx = [i for i, b in enumerate(ep.beats()) if start - cfg.eps <= b.start < end - cfg.eps]
    first = inside_idx[0] if inside_idx else None
    last_say = None
    for i in inside_idx:
        if ep.beats()[i].kind != "camera":
            last_say = i
    for i, b in enumerate(ep.beats()):
        inside = first is not None and i in inside_idx
        if b.kind == "dialogue":
            body = f"<b>{html.escape(b.speaker or '')}</b>{(' (' + html.escape(b.emotion) + ')') if b.emotion else ''}: {html.escape(b.text)}"
            cls = ""
        elif b.kind == "camera":
            body = f"<i>[camera] {html.escape(b.text)}</i>"
            cls = " cam"
        elif b.kind == "sound":
            body = f"<i>[sound] {html.escape(b.text)}</i>"
            cls = ""
        else:
            body = f"<i>[action] {html.escape(b.text)}</i>"
            cls = ""
        mark = ""
        anchor = ""
        if inside and i == first:
            mark = '<span class="mk s">&#9650; CLIP STARTS</span>'
            anchor = ' id="clipstart"'
        if inside and i == last_say:
            mark += '<span class="mk e">&#9660; CLIP ENDS</span>'
        rows.append(f'<div class="ln{" in" if inside else ""}{cls}"{anchor}><code>{fmt_ts(b.start)}</code>{body}{mark}</div>')
    css = ("*{box-sizing:border-box}body{margin:0;background:#14152a;color:#f3f3fa;font-family:'Segoe UI',Arial,sans-serif}"
           f"#box{{height:{height - 6}px;overflow-y:auto;position:relative;padding:8px;border:1px solid #2a2b4a;border-radius:12px}}"
           ".ln{padding:4px 9px;border-radius:6px;font-size:14px;margin-bottom:2px;color:#9a9bbd;line-height:1.45}"
           ".ln b{color:#e9eaf8}.ln code{background:rgba(255,255,255,.1);padding:0 5px;border-radius:4px;margin-right:7px;font-size:12px}"
           ".ln.cam{opacity:.8}.ln.in{background:#fff3a3;color:#111}.ln.in b{color:#000}.ln.in code{background:rgba(0,0,0,.12)}"
           ".mk{float:right;font-size:11px;font-weight:800;padding:1px 9px;border-radius:10px;margin-left:8px}"
           ".mk.s{background:#2ecc88;color:#06281a}.mk.e{background:#ff4d6d;color:#fff}")
    js = ("var b=document.getElementById('box'),e=document.getElementById('clipstart');"
          "if(b&&e){b.scrollTop=Math.max(0,e.offsetTop-90);}")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body><div id='box'>{''.join(rows)}</div><script>{js}</script></body></html>"
