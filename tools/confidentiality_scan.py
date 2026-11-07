"""Confidentiality scan: make sure NOTHING derived from the private input pack is inside the public repo.

It learns character names and distinctive dialogue fragments from the pack (never printed in full), then searches every
text file in the repo. Exit code 1 if anything is found.

Run:  python tools/confidentiality_scan.py --pack path/to/pack.zip --repo .
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from promoforge.ingestion import load_input  # noqa: E402

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".promoforge_cache", ".pytest_cache", "submission_private", "outputs", "node_modules"}
TEXT_EXT = {".py", ".md", ".txt", ".json", ".csv", ".toml", ".yml", ".yaml", ".example", ".cfg", ".ini", ".html", ".fountain", ""}
GENERIC = {"lord", "lady", "duke", "duchess", "man", "woman", "mother", "father", "stranger", "voice", "guard", "guards", "mysterious",
           "dowager", "noble", "nobleman", "noblewoman", "blond", "bearded", "old", "young", "doctor", "captain", "officer", "judge",
           "bishop", "priest", "butler", "maid", "servant", "narrator", "soldier", "constable", "driver", "elder", "girl", "boy",
           "king", "queen", "prince", "princess", "council", "crown", "england", "british", "catholic", "english", "former",
           "bald", "cart", "fighter", "gold", "gown", "groom", "high", "housekeeper", "informant", "loyalist", "manor",
           "matriarch", "official", "peasant", "police", "royal", "scout", "screen", "thug", "townsman", "villager", "west",
           "wing", "aristocratic"}


def _mid_sentence_caps(text: str):
    for m in re.finditer(r"\b([A-Z][a-z]{3,})(?:'s)?\b", text):
        before = text[:m.start()].rstrip()
        if before and before[-1] not in ".!?\u2026\"\u201c\u2014-:":
            yield m.group(1).lower()


def learn(pack: Path):
    from promoforge.lexicons import COMMON_CAPS
    eps = load_input(pack).episodes
    names: Counter = Counter()
    for ep in eps:
        for b in ep.beats():
            if b.speaker:
                for t in re.split(r"[^A-Za-z]+", b.speaker):
                    if len(t) >= 4:
                        names[t.lower()] += 2
            if b.kind == "dialogue":
                names.update(_mid_sentence_caps(b.text))
        for text in (ep.logline, ep.continuity):
            names.update(_mid_sentence_caps(text))
    skip = GENERIC | COMMON_CAPS | {"episode", "scene"}
    common = {w for w, c in names.items() if c >= 4 and w not in skip}
    shingles: set[str] = set()
    for ep in eps:
        for b in ep.beats():
            if b.kind == "dialogue":
                w = re.findall(r"[a-z']+", b.text.lower())
                for i in range(0, max(0, len(w) - 5)):
                    shingles.add(" ".join(w[i:i + 6]))
    return common, shingles


def scan(repo: Path, names: set[str], shingles: set[str]) -> list[str]:
    hits = []
    pat = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b", re.I) if names else None
    for f in repo.rglob("*"):
        if not f.is_file() or any(part in SKIP_DIRS for part in f.relative_to(repo).parts):
            continue
        rel = f.relative_to(repo).as_posix()
        if f.suffix.lower() == ".png" and rel.startswith("docs/screenshots/"):
            continue        # screenshots of the invented sample stories are intended
        if f.suffix.lower() in {".zip", ".pdf", ".png", ".jpg"}:
            hits.append(f"{f.relative_to(repo)}: binary/archive file in repo (check it is not the input pack)")
            continue
        if f.suffix.lower() not in TEXT_EXT:
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = f.relative_to(repo)
        if pat:
            m = pat.findall(txt)
            if m:
                hits.append(f"{rel}: contains {len(m)} character-name match(es) from the pack (e.g. '{m[0][:2]}...')")
        low = " ".join(re.findall(r"[a-z']+", txt.lower()))
        n = sum(1 for s in shingles if s in low)
        if n:
            hits.append(f"{rel}: contains {n} dialogue fragment(s) (6+ words) from the pack")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--repo", default=str(ROOT))
    a = ap.parse_args()
    names, shingles = learn(Path(a.pack))
    print(f"Learned {len(names)} name tokens and {len(shingles)} dialogue fragments from the pack (not shown).")
    hits = scan(Path(a.repo), names, shingles)
    if hits:
        print("FAIL: possible confidential material in the repo:")
        for h in hits:
            print("  - " + h)
        return 1
    print("PASS: no pack-derived names or dialogue found in the repo files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
