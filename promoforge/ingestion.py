"""Load a ZIP / folder / TXT / MD / PDF into a list of Episodes (dedupe, encodings, numbering)."""
from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, DEFAULT
from .models import Episode
from .parser import detect_format, is_english, number_from_filename, parse_episode, subtitles_to_inline

TEXT_EXT = {".txt", ".md", ".markdown", ".fountain", ".text"}
SUBTITLE_EXT = {".srt", ".vtt"}
SUPPORTED = TEXT_EXT | SUBTITLE_EXT | {".pdf", ".docx"}


@dataclass
class IngestResult:
    episodes: list[Episode] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_seen: int = 0
    files_skipped: int = 0


def decode_bytes(b: bytes) -> str:
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        return b.decode("utf-16", errors="replace")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader  # imported lazily: only needed for PDF input
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def docx_to_text(data: bytes) -> str:
    """Plain text of a Word file, one line per paragraph (no extra package needed: a .docx is a zip of XML)."""
    import xml.etree.ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for para in root.iter(ns + "p"):
        parts = []
        for node in para.iter():
            if node.tag == ns + "t" and node.text:
                parts.append(node.text)
            elif node.tag == ns + "tab":
                parts.append("\t")
            elif node.tag == ns + "br":
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _collect(path: Path) -> list[tuple[str, bytes]]:
    items: list[tuple[str, bytes]] = []
    if path.is_dir():
        for p in sorted(path.rglob("*"), key=lambda q: _natural_key(str(q))):
            if p.is_file():
                items.append((str(p.relative_to(path)), p.read_bytes()))
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for n in sorted(z.namelist(), key=_natural_key):
                if n.endswith("/"):
                    continue
                items.append((n, z.read(n)))
    else:
        items.append((path.name, path.read_bytes()))
    return items


MAX_ZIP_ENTRIES = 500
MAX_ZIP_ENTRY_BYTES = 60 * 1024 * 1024


def _expand_zips(items: list[tuple[str, bytes]], res: "IngestResult") -> list[tuple[str, bytes]]:
    """A ZIP that arrives as an uploaded file (the web page) is opened here, so a ZIP of all episodes works the same
    as on the command line. A ZIP inside a ZIP is not opened."""
    out: list[tuple[str, bytes]] = []
    for name, data in items:
        if os.path.splitext(name)[1].lower() != ".zip":
            out.append((name, data))
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = [i for i in z.infolist() if not i.is_dir()]
                if len(infos) > MAX_ZIP_ENTRIES:
                    res.warnings.append(f"{name}: has {len(infos)} files; only the first {MAX_ZIP_ENTRIES} were read.")
                for i in infos[:MAX_ZIP_ENTRIES]:
                    if i.file_size > MAX_ZIP_ENTRY_BYTES:
                        res.warnings.append(f"{i.filename}: too large; skipped")
                        continue
                    out.append((i.filename, z.read(i)))
        except zipfile.BadZipFile:
            res.warnings.append(f"{name}: could not open this ZIP file; skipped")
    return out


def load_bytes_items(items: list[tuple[str, bytes]], cfg: Config = DEFAULT) -> IngestResult:
    """items = [(filename, raw bytes)]. Used by both the CLI and the Streamlit uploader."""
    res = IngestResult()
    items = _expand_zips(items, res)
    seen_hash: dict[str, str] = {}
    parsed: list[tuple[str, Episode]] = []
    items = sorted(items, key=lambda it: _natural_key(it[0]))
    order = 0
    for name, data in items:
        res.files_seen += 1
        base = os.path.basename(name)
        ext = os.path.splitext(base)[1].lower()
        if "__MACOSX" in name or base.startswith(".") or ext not in SUPPORTED:
            res.files_skipped += 1
            continue
        try:
            if ext == ".pdf":
                text = pdf_to_text(data)
            elif ext == ".docx":
                text = docx_to_text(data)
            else:
                text = decode_bytes(data)
        except Exception as e:  # noqa: BLE001
            res.warnings.append(f"{name}: could not read ({type(e).__name__}); skipped")
            res.files_skipped += 1
            continue
        if ext == ".pdf":
            res.warnings.append(f"{name}: PDF text extraction loses blank lines; parsed in compact mode (check results).")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if ext in SUBTITLE_EXT:
            text, named = subtitles_to_inline(text)
            if text and not named:
                res.warnings.append(f"{name}: subtitle file has no speaker names; speakers show as 'Voice' (speaker-based checks are limited).")
        if not text.strip():
            res.warnings.append(f"{name}: empty file; skipped")
            res.files_skipped += 1
            continue
        h = hashlib.sha1(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()
        if h in seen_hash:
            res.warnings.append(f"{name}: duplicate of {seen_hash[h]}; skipped")
            res.files_skipped += 1
            continue
        seen_hash[h] = name
        order += 1
        if not is_english(text):
            res.warnings.append(f"{name}: text does not look English; the rules-only cue lists are English-only, scores will be unreliable.")
        fmt = detect_format(text)
        ep = parse_episode(text, source=name, default_number=order, fmt=fmt, cfg=cfg)
        for w in ep.warnings:
            res.warnings.append(f"{name}: {w}")
        parsed.append((name, ep))

    # numbering: keep header/filename numbers, fix duplicates
    used: set[int] = set()
    out: list[Episode] = []
    for name, ep in sorted(parsed, key=lambda x: (x[1].number, _natural_key(x[0]))):
        if ep.number in used:
            new = max(used) + 1
            res.warnings.append(f"{name}: episode number {ep.number} already used; renumbered to {new}")
            _renumber(ep, new)
        used.add(ep.number)
        out.append(ep)
    out.sort(key=lambda e: e.number)
    res.episodes = out
    # beat-ID uniqueness safety net
    ids = [b.id for e in out for b in e.beats()]
    if len(ids) != len(set(ids)):
        res.warnings.append("Beat IDs were not unique after parsing (this should not happen).")
    return res


def _renumber(ep: Episode, new: int) -> None:
    ep.number = new
    for s in ep.scenes:
        for i, b in enumerate(s.beats, 1):
            b.episode = new
            b.id = f"E{new:03d}-S{s.index:02d}-B{i:03d}"
    ep.invalidate()


def load_input(path: str | os.PathLike, cfg: Config = DEFAULT) -> IngestResult:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input not found: {p}")
    return load_bytes_items(_collect(p), cfg)
