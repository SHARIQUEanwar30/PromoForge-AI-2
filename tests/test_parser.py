import io
import zipfile

from promoforge.ingestion import load_bytes_items, load_input
from promoforge.parser import detect_format, parse_episode, parse_ts

LABELLED = """EPISODE NUMBER: Episode 7
EPISODE LOGLINE: A test.
CONTINUITY NOTES: Picks up directly from Episode 6.

--- SCRIPT START ---

SCENE 01
Scene heading: INT. HALL - NIGHT
Scene start: 00:00.00
Scene end: 00:20.00

Actions and dialogue:

**CAMERA:**
Start: (00:00.00) | End: (00:03.00)
Wide shot of the hall.

**ANNA (Cold, Sharp):**
Start: (00:01.00) | End: (00:02.50)
"Get out of my house!"

**BEN (O.S.) (Gasping):**
Start: (00:03.00) | End: (00:04.50)
"No."

**SOUND FX:**
Start: (00:05.00) | End: (00:06.00)
A door slams.

--- SCRIPT END ---
"""


def test_parse_ts_variants():
    assert parse_ts("01:02.50") == 62.5
    assert parse_ts("(00:07.20)") == 7.2
    assert parse_ts("1:01:01") == 3661


def test_labelled_basic_and_double_parentheses():
    assert detect_format(LABELLED) == "labelled"
    ep = parse_episode(LABELLED, "episode-007.txt")
    assert ep.number == 7 and ep.fmt == "labelled"
    kinds = [b.kind for b in ep.beats()]
    assert kinds == ["camera", "dialogue", "dialogue", "sound"]
    ben = [b for b in ep.beats() if b.speaker == "Ben"][0]
    assert ben.text == "No." and ben.emotion == "Gasping"   # '(O.S.) (Gasping)' handled
    assert "Continuity" or ep.continuity.startswith("Picks up")


def test_labelled_compact_mode_no_blank_lines():
    compact = "\n".join(l for l in LABELLED.splitlines() if l.strip())
    ep = parse_episode(compact, "episode-007.txt")
    assert len(ep.beats()) == 4


def test_inline_format(sample_dirs):
    r = load_input(sample_dirs["story_inline"])
    assert [e.fmt for e in r.episodes] == ["inline"] * 3
    b = r.episodes[0].beats()
    assert any(x.kind == "dialogue" and x.speaker for x in b)
    assert not r.episodes[0].timing_estimated


def test_fountain_format_estimates_timing(sample_dirs):
    r = load_input(sample_dirs["story_fountain"])
    ep = r.episodes[0]
    assert ep.fmt == "fountain" and ep.timing_estimated
    assert all(b.timing_estimated for b in ep.beats())
    assert any("ESTIMATED" in w for w in r.warnings)
    d = [b for b in ep.beats() if b.kind == "dialogue"]
    assert d and all(b.end > b.start for b in d)


def test_prose_fallback():
    text = 'Episode 3\nMara stood at the gate. "Open the door," said Mara. The rain fell harder. "Never," said Father.'
    ep = parse_episode(text, "x.txt")
    assert ep.fmt == "prose" and ep.timing_estimated
    assert any(b.kind == "dialogue" for b in ep.beats())


def test_beat_ids_unique_across_scenes_and_episodes(sample_dirs):
    for d in sample_dirs.values():
        r = load_input(d)
        ids = [b.id for e in r.episodes for b in e.beats()]
        assert len(ids) == len(set(ids))


def test_beat_ids_include_episode_and_scene():
    ep = parse_episode(LABELLED, "episode-007.txt")
    assert all(b.id.startswith("E007-S01-B") for b in ep.beats())


def test_zip_ingestion_dedupe_and_junk(sample_dirs):
    buf = io.BytesIO()
    src = (sample_dirs["story_labelled"] / "episode-001.txt").read_text(encoding="utf-8")
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pack/episode-001.txt", src)
        z.writestr("pack/episode-001 copy.txt", src)          # exact duplicate
        z.writestr("__MACOSX/pack/._episode-001.txt", "junk")
        z.writestr("pack/readme.docx", "x")
    p = sample_dirs["story_labelled"].parent / "_tmp_test.zip"
    p.write_bytes(buf.getvalue())
    try:
        r = load_input(p)
    finally:
        p.unlink()
    assert len(r.episodes) == 1
    assert any("duplicate" in w for w in r.warnings)


def test_bom_and_encodings():
    from promoforge.ingestion import decode_bytes
    assert decode_bytes("﻿hello".encode("utf-8")).startswith("hello")
    assert decode_bytes("café".encode("cp1252")) == "café"


def test_duplicate_episode_numbers_are_renumbered():
    a = ("EPISODE NUMBER: Episode 1\n" + LABELLED.split("\n", 1)[1]).encode()
    b = a.replace(b"Get out of my house", b"Leave this place now")
    r = load_bytes_items([("a.txt", a), ("b.txt", b)])
    assert sorted(e.number for e in r.episodes) == [1, 2]
    assert any("renumbered" in w for w in r.warnings)
    ids = [x.id for e in r.episodes for x in e.beats()]
    assert len(ids) == len(set(ids))


def test_non_english_warning():
    es = ("Episodio 1\n" + "\n".join(f"[00:{i:02d} - 00:{i + 1:02d}] ANA: el perro come la manzana en la casa de mi madre y ella dice que no" for i in range(10))).encode()
    r = load_bytes_items([("es.txt", es)])
    assert any("English" in w for w in r.warnings)


def test_pdf_round_trip():
    """A screenplay exported to PDF loses blank lines; compact mode must still parse it."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in [l for l in LABELLED.splitlines() if l.strip()]:
        c.drawString(40, y, line.replace("–", "-"))
        y -= 14
    c.save()
    r = load_bytes_items([("episode-007.pdf", buf.getvalue())])
    assert len(r.episodes) == 1
    ep = r.episodes[0]
    assert ep.number == 7 and len(ep.beats()) == 4
    assert any("compact mode" in w for w in r.warnings)
