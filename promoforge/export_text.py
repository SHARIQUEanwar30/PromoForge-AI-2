"""One plain .txt file per promo, written in the same style as the episode files that were uploaded.

Kuku-style episodes (labelled blocks with Start/End times) come back as labelled blocks; inline-timestamp episodes
come back as inline lines; screenplay (Fountain) and prose episodes come back as plain screenplay lines. Times inside
a file are the ORIGINAL episode times, so an editor can find the same spot in the full episode.

The files contain the story's text. They are for the person who uploaded the story, not for publishing.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from .config import Config, DEFAULT
from .models import Beat, Episode, Promo, Segment, fmt_ts

KIND_LABEL = {"camera": "CAMERA", "action": "ACTION", "sound": "SOUND FX"}


def promo_filename(p: Promo, width: int = 2) -> str:
    eps = list(dict.fromkeys(s.episode for s in p.segments))
    ep = f"ep{eps[0]:03d}" if len(eps) == 1 else "ep" + "-".join(f"{e:03d}" for e in eps)
    return f"promo_{p.rank:0{width}d}_{ep}.txt"


def clip_beats(ep: Episode, seg: Segment, cfg: Config = DEFAULT) -> list[Beat]:
    return [b for b in ep.beats() if seg.start - cfg.eps <= b.start < seg.end - cfg.eps]


def _header(p: Promo, emap: dict[int, Episode]) -> list[str]:
    eps = list(dict.fromkeys(s.episode for s in p.segments))
    lines = [f"PROMO {p.rank}",
             "EPISODE NUMBER: " + " + ".join(f"Episode {e}" for e in eps)]
    if len(p.segments) == 1:
        s = p.segments[0]
        lines.append(f"CLIP: {fmt_ts(s.start)} - {fmt_ts(s.end)} ({s.duration:.1f} s)")
    else:
        for i, s in enumerate(p.segments, 1):
            lines.append(f"CLIP PART {i}: Episode {s.episode} {fmt_ts(s.start)} - {fmt_ts(s.end)} ({s.duration:.1f} s)")
        lines.append(f"TOTAL: {p.duration:.1f} s")
    lines.append(f"HOOK: {p.hook}")
    lines.append(f"CLIFFHANGER: {p.cliffhanger}")
    if p.why:
        lines.append(f"WHY IT WORKS: {p.why}")
    if p.cut_note:
        lines.append(f"EDITING TIP: {p.cut_note}")
    if any(emap[s.episode].timing_estimated for s in p.segments if s.episode in emap):
        lines.append("NOTE: this story has no timestamps, so the times are ESTIMATED from word counts.")
    return lines


def _labelled(ep: Episode, beats: list[Beat]) -> list[str]:
    out: list[str] = []
    last_scene = None
    for b in beats:
        if b.scene != last_scene:
            sc = ep.scene(b.scene)
            out += [f"SCENE {b.scene:02d}"]
            if sc is not None and sc.heading:
                out += [f"Scene heading: {sc.heading}"]
            out += [""]
            last_scene = b.scene
        if b.kind == "dialogue":
            emo = f" ({b.emotion})" if b.emotion else ""
            out += [f"**{(b.speaker or 'VOICE').upper()}{emo}:**", f"Start: ({fmt_ts(b.start)}) | End: ({fmt_ts(b.end)})", f'"{b.text}"', ""]
        else:
            out += [f"**{KIND_LABEL.get(b.kind, 'ACTION')}:**", f"Start: ({fmt_ts(b.start)}) | End: ({fmt_ts(b.end)})", b.text, ""]
    return out


def _inline(ep: Episode, beats: list[Beat]) -> list[str]:
    out: list[str] = []
    last_scene = None
    for b in beats:
        if b.scene != last_scene:
            sc = ep.scene(b.scene)
            head = f" - {sc.heading}" if sc is not None and sc.heading else ""
            out += [f"## SCENE {b.scene}{head}"]
            last_scene = b.scene
        stamp = f"[{fmt_ts(b.start)} - {fmt_ts(b.end)}]"
        if b.kind == "dialogue":
            emo = f" ({b.emotion})" if b.emotion else ""
            out.append(f"{stamp} {b.speaker or 'Voice'}{emo}: {b.text}")
        elif b.kind == "sound":
            out.append(f"{stamp} SOUND FX: {b.text}")
        else:
            out.append(f"{stamp} {b.text}")
    return out


def _screenplay(ep: Episode, beats: list[Beat], headings: bool) -> list[str]:
    out: list[str] = []
    last_scene = None
    for b in beats:
        if headings and b.scene != last_scene:
            sc = ep.scene(b.scene)
            if sc is not None and sc.heading:
                out += [sc.heading.upper(), ""]
            last_scene = b.scene
        if b.kind == "dialogue":
            if headings:
                out.append((b.speaker or "VOICE").upper())
                if b.emotion:
                    out.append(f"({b.emotion.lower()})")
                out += [b.text, ""]
            else:
                out += [f'{b.speaker or "Voice"}: "{b.text}"', ""]
        elif b.kind == "sound":
            out += [f"SOUND FX: {b.text}", ""]
        else:
            out += [b.text, ""]
    return out


def promo_text(p: Promo, emap: dict[int, Episode], cfg: Config = DEFAULT) -> str:
    """The text of one promo file."""
    lines = _header(p, emap) + [""]
    multi = len(p.segments) > 1
    first_fmt = emap[p.segments[0].episode].fmt if p.segments[0].episode in emap else "prose"
    lines.append("--- SCRIPT START ---" if first_fmt == "labelled" else "--- SCRIPT ---")
    lines.append("")
    for i, s in enumerate(p.segments, 1):
        ep = emap[s.episode]
        beats = clip_beats(ep, s, cfg)
        if multi:
            lines += [f"--- PART {i}: EPISODE {s.episode} ---", ""]
        if ep.fmt == "labelled":
            lines += _labelled(ep, beats)
        elif ep.fmt == "inline":
            lines += _inline(ep, beats) + [""]
        elif ep.fmt == "fountain":
            lines += _screenplay(ep, beats, headings=True)
        else:
            lines += _screenplay(ep, beats, headings=False)
    lines.append("--- SCRIPT END ---" if first_fmt == "labelled" else "--- END ---")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip() + "\n"


def promo_text_files(promos: list[Promo], emap: dict[int, Episode], cfg: Config = DEFAULT) -> list[tuple[str, str]]:
    """[(file name, text)] in rank order."""
    width = max(2, len(str(max((p.rank for p in promos), default=1))))
    return [(promo_filename(p, width), promo_text(p, emap, cfg)) for p in promos]


def zip_bytes(files: list[tuple[str, str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files:
            z.writestr(name, text.encode("utf-8"))
    return buf.getvalue()


def write_promo_texts(promos: list[Promo], emap: dict[int, Episode], out_dir, cfg: Config = DEFAULT) -> list[Path]:
    """Writes out_dir/promo_texts/*.txt and out_dir/promo_texts.zip. Returns the paths of the text files."""
    out = Path(out_dir)
    folder = out / "promo_texts"
    folder.mkdir(parents=True, exist_ok=True)
    files = promo_text_files(promos, emap, cfg)
    paths = []
    for name, text in files:
        path = folder / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    (out / "promo_texts.zip").write_bytes(zip_bytes(files))
    return paths
