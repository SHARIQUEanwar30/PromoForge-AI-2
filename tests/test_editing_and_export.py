"""Tests for the Editing Desk helpers and the one-text-file-per-promo export."""
import io
import zipfile
from pathlib import Path

import pytest

from promoforge.editing import (STEP, apply_edit, check_edit, effective_promos, line_at, nudge_time, script_view_html)
from promoforge.export_text import (promo_filename, promo_text, promo_text_files, write_promo_texts, zip_bytes)
from promoforge.ingestion import load_input
from promoforge.llm_provider import Settings
from promoforge.parser import parse_episode
from promoforge.pipeline import run_pipeline

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture(scope="module", params=["story_labelled", "story_inline", "story_fountain"])
def run(request):
    res = run_pipeline(input_path=SAMPLES / request.param, settings=Settings(provider="none"), top_n=8)
    return request.param, res, {e.number: e for e in res.episodes}


def _single(res):
    return next(p for p in res.promos if len(p.segments) == 1)


# ---------------------------------------------------------------- checks and moves

def test_check_edit_accepts_the_tools_own_pick(run):
    _, res, emap = run
    p = _single(res)
    s = p.segments[0]
    ok, msg = check_edit(emap[s.episode], emap, s.start, s.end)
    assert ok and "no line cut in half" in msg


def test_check_edit_refuses_too_short_and_too_long_in_plain_words(run):
    _, res, emap = run
    p = _single(res)
    s = p.segments[0]
    ep = emap[s.episode]
    ok, msg = check_edit(ep, emap, s.start, s.start + 10.0)
    assert not ok and msg.startswith("Not changed") and "between 20 and 60 seconds" in msg
    if ep.duration >= 62:                                     # (the short samples are not long enough to test this one)
        ok, msg = check_edit(ep, emap, 0.0, 61.5)
        assert not ok and "between 20 and 60 seconds" in msg
    ok, msg = check_edit(ep, emap, s.start, ep.duration + 30)
    assert not ok and msg.startswith("Not changed") and "outside the episode" in msg


def test_check_edit_refuses_a_cut_inside_a_spoken_line_and_suggests_the_edges(run):
    _, res, emap = run
    p = _single(res)
    s = p.segments[0]
    ep = emap[s.episode]
    line = next(b for b in ep.beats() if b.kind == "dialogue" and b.end - b.start > 1.2 and b.start > s.start)
    mid = round((line.start + line.end) / 2, 2)
    ok, msg = check_edit(ep, emap, s.start, mid)
    if mid - s.start >= 20:                                   # only then is the line the reason for the refusal
        assert not ok and "inside the line" in msg and f"{line.start:.2f}" in msg


def test_nudge_never_lands_inside_a_line_and_moves_the_right_way(run):
    _, res, emap = run
    p = _single(res)
    s = p.segments[0]
    ep = emap[s.episode]
    for which, cur in (("start", s.start), ("end", s.end)):
        for delta in (STEP, -STEP):
            t, slid = nudge_time(ep, which, cur, delta)
            assert line_at(ep, t) is None
            assert (t >= cur - 1e-6) if delta > 0 else (t <= cur + 1e-6)
            if not slid:
                assert t == pytest.approx(min(max(cur + delta, 0.0), ep.duration), abs=0.011)


def test_apply_edit_rebuilds_the_clip_and_leaves_the_original_alone(run):
    _, res, emap = run
    p = _single(res)
    s = p.segments[0]
    ep = emap[s.episode]
    new_end, _ = nudge_time(ep, "end", s.end, -STEP)
    ok, _ = check_edit(ep, emap, s.start, new_end)
    if not ok or abs(new_end - s.end) < 0.01:
        pytest.skip("this sample has no valid shorter cut one step earlier")
    q = apply_edit(p, emap, s.start, new_end)
    assert q.segments[0].end == pytest.approx(new_end) and q.validation.ok
    assert p.segments[0].end == pytest.approx(s.end)                  # original untouched
    assert any("edited" in n.lower() for n in q.notes)
    assert q.transcript and q.transcript[-1]["start"] < new_end


def test_apply_edit_with_same_times_returns_the_same_promo(run):
    _, res, emap = run
    p = _single(res)
    assert apply_edit(p, emap, p.segments[0].start, p.segments[0].end) is p


def test_effective_promos_applies_edits_and_kept_only(run):
    _, res, emap = run
    p = _single(res)
    s = p.segments[0]
    ep = emap[s.episode]
    new_end, _ = nudge_time(ep, "end", s.end, -STEP)
    rv = {p.promo_id: {"status": "approved", "edit": {"episode": s.episode, "start": s.start, "end": new_end}}}
    kept = effective_promos(res.promos, emap, rv, kept_only=True)
    assert [x.promo_id for x in kept] == [p.promo_id]
    assert len(effective_promos(res.promos, emap, rv)) == len(res.promos)
    assert len(effective_promos(res.promos, emap, {})) == len(res.promos)


def test_script_view_marks_the_clip_and_scrolls_to_it(run):
    _, res, emap = run
    p = _single(res)
    s = p.segments[0]
    page = script_view_html(emap[s.episode], s.start, s.end)
    assert 'id="clipstart"' in page and "CLIP STARTS" in page and "CLIP ENDS" in page and "scrollTop" in page
    assert page.count('class="ln in') >= 2


# ---------------------------------------------------------------- the text files

def test_one_file_per_promo_with_hook_cliffhanger_and_the_clip_lines(run):
    _, res, emap = run
    files = promo_text_files(res.promos, emap)
    assert len(files) == len(res.promos) and len({n for n, _ in files}) == len(files)
    for (name, text), p in zip(files, res.promos):
        assert name.startswith("promo_") and name.endswith(".txt") and ":" not in name
        assert f"PROMO {p.rank}" in text and "HOOK:" in text and "CLIFFHANGER:" in text
        said = [t for t in p.transcript if t["kind"] == "dialogue"]
        assert said and all(t["text"] in text for t in said)


def test_a_promo_from_two_episodes_is_one_file_with_two_parts(run):
    _, res, emap = run
    two = next((p for p in res.promos if len({s.episode for s in p.segments}) > 1), None)
    if two is None:
        pytest.skip("no two-episode promo in this sample")
    text = promo_text(two, emap)
    assert "--- PART 1" in text and "--- PART 2" in text
    assert promo_filename(two).count("-") == 1 and promo_filename(two).startswith("promo_")


def test_the_text_file_is_written_in_the_same_style_as_the_input_and_reads_back(run):
    """Round trip: parse the promo file with the engine's own reader; it finds the same format and the same lines."""
    name, res, emap = run
    p = _single(res)
    text = promo_text(p, emap)
    ep0 = emap[p.segments[0].episode]
    back = parse_episode(text, source="promo.txt")
    assert back.fmt == ep0.fmt
    said_before = [t["text"] for t in p.transcript if t["kind"] == "dialogue"]
    said_after = [b.text for b in back.beats() if b.kind == "dialogue"]
    assert said_after == said_before
    if ep0.fmt in ("labelled", "inline"):                      # times are kept as in the episode
        first = [b for b in back.beats() if b.kind == "dialogue"][0]
        orig = [b for b in ep0.beats() if b.kind == "dialogue" and b.text == first.text][0]
        assert first.start == pytest.approx(orig.start, abs=0.011)


def test_estimated_times_are_said_in_the_file():
    res = run_pipeline(input_path=SAMPLES / "story_fountain", settings=Settings(provider="none"), top_n=5)
    emap = {e.number: e for e in res.episodes}
    assert "ESTIMATED" in promo_text(res.promos[0], emap)


def test_zip_and_folder_have_every_file(tmp_path, run):
    _, res, emap = run
    files = promo_text_files(res.promos, emap)
    z = zipfile.ZipFile(io.BytesIO(zip_bytes(files)))
    assert sorted(z.namelist()) == sorted(n for n, _ in files)
    paths = write_promo_texts(res.promos, emap, tmp_path)
    assert len(paths) == len(files) and (tmp_path / "promo_texts.zip").exists()
    assert all(p.read_text(encoding="utf-8").startswith("PROMO ") for p in paths)


def test_the_pipeline_writes_the_text_files_with_the_other_outputs(tmp_path):
    from promoforge.pipeline import export_run
    res = run_pipeline(input_path=SAMPLES / "story_labelled", settings=Settings(provider="none"), top_n=5)
    export_run(res, tmp_path)
    assert (tmp_path / "promo_texts.zip").exists() and len(list((tmp_path / "promo_texts").glob("*.txt"))) == len(res.promos)


# ---------------------------------------------------------------- a ZIP uploaded on the web page

def test_a_zip_uploaded_as_bytes_is_opened_like_on_the_command_line(tmp_path):
    from promoforge.ingestion import load_bytes_items
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted((SAMPLES / "story_labelled").glob("*.txt")):
            z.writestr("folder/" + f.name, f.read_bytes())
        z.writestr("__MACOSX/._junk.txt", b"x")
    res = load_bytes_items([("all_episodes.zip", buf.getvalue())])
    assert len(res.episodes) == len(list((SAMPLES / "story_labelled").glob("*.txt")))
    assert load_bytes_items([("broken.zip", b"not a zip")]).warnings
