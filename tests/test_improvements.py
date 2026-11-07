"""Tests for the quality upgrade: subtitle/Word input, continuity fallback, quality floor, look-ahead, spoiler control,
and the AI side (rubric prompt, lines after the cut, rescaling, rank bonus, moment scan, call budget)."""
import io
import json
import zipfile

import pytest

from promoforge.candidate_generator import generate_candidates
from promoforge.config import DEFAULT, WEIGHTS
from promoforge.ingestion import docx_to_text, load_bytes_items
from promoforge.llm_judge import (JUDGE_SYSTEM, MIN_RESCALE, _batch_ranks, _rescale, build_prompt, judge_promos)
from promoforge.llm_provider import LLMClient, Provider, Completion, Settings
from promoforge.llm_scan import plan_calls, scan_episodes
from promoforge.models import Episode
from promoforge.parser import parse_episode, subtitles_to_inline
from promoforge.pipeline import run_pipeline
from promoforge.ranking import candidate_to_promo, mmr_select, quality_floor
from promoforge.scoring import compute_context, score_segments
from promoforge.validator import may_join, show_has_continuity_notes


def _client(tmp_path, mode="ok", max_calls=200):
    s = Settings(provider="mock", model=f"mock-{mode}", cache_dir=str(tmp_path / "cache"), rpm=6000, max_calls=max_calls)
    return LLMClient(s, sleep=lambda x: None), s


# ---------------------------------------------------------------- input formats

SRT = """1
00:00:01,000 --> 00:00:03,500
MARA: You lied to me.

2
00:00:04,000 --> 00:00:06,000
[door slams]

3
00:00:06,500 --> 00:00:09,000
DEV: <i>Open the safe. Now!</i>

4
00:00:30,000 --> 00:00:33,000
MARA: Who sent you?
"""

VTT = """WEBVTT

00:01.000 --> 00:03.500
MARA: You lied to me.

00:04.000 --> 00:06.000
DEV: Why now?

00:06.500 --> 00:09.000
MARA: Because I found the letter.
"""


def test_srt_becomes_inline_lines_with_speakers_and_sound():
    text, named = subtitles_to_inline(SRT)
    assert named
    assert "[00:01.00 - 00:03.50] MARA: You lied to me." in text
    assert "SOUND: door slams" in text
    assert "<i>" not in text and "DEV: Open the safe. Now!" in text
    assert text.count("SCENE") == 2          # the 21 s gap starts a new scene


def test_vtt_without_hours_is_read():
    text, named = subtitles_to_inline(VTT)
    assert named and "[00:04.00 - 00:06.00] DEV: Why now?" in text


def test_subtitle_file_loads_as_episode_and_warns_when_no_speakers():
    plain = SRT.replace("MARA: ", "").replace("DEV: ", "")
    res = load_bytes_items([("ep1.srt", plain.encode())])
    assert len(res.episodes) == 1 and len(res.episodes[0].beats()) >= 3
    assert any("no speaker names" in w for w in res.warnings)
    res2 = load_bytes_items([("ep1.srt", SRT.encode()), ("ep2.vtt", VTT.encode())])
    assert [e.number for e in res2.episodes] == [1, 2]


def _docx(lines):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{l}</w:t></w:r></w:p>" for l in lines)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", f'<w:document {ns}><w:body>{body}</w:body></w:document>')
    return b.getvalue()


def test_docx_text_is_extracted_and_parsed():
    lines = ["[00:01.00 - 00:03.00] MARA: You lied to me.", "[00:03.50 - 00:05.00] DEV: Why now?",
             "[00:05.50 - 00:08.00] MARA: Because of the letter."]
    assert docx_to_text(_docx(lines)).splitlines() == lines
    res = load_bytes_items([("ep3.docx", _docx(lines))])
    assert len(res.episodes) == 1 and res.episodes[0].number == 3
    assert [b.speaker for b in res.episodes[0].beats() if b.kind == "dialogue"] == ["Mara", "Dev", "Mara"]


def test_broken_docx_is_skipped_not_a_crash():
    res = load_bytes_items([("bad.docx", b"not a zip")])
    assert res.episodes == [] and res.files_skipped


# ---------------------------------------------------------------- continuity fallback

def _eps_without_notes(labelled):
    eps = [e.model_copy(deep=True) for e in labelled]
    for e in eps:
        e.continuity = ""
    return eps


def test_without_any_continuity_notes_consecutive_episodes_may_join_but_are_marked_assumed(labelled):
    eps = _eps_without_notes(labelled)
    assert not show_has_continuity_notes(eps)
    assert may_join(1, eps[1], eps) == (True, True)
    assert may_join(1, eps[2], eps) == (False, True)       # not the next episode


def test_with_notes_present_a_non_continuing_episode_cannot_join(labelled):
    eps = [e.model_copy(deep=True) for e in labelled]
    eps[1].continuity = "A new storyline starts here."
    assert show_has_continuity_notes(eps)
    assert may_join(1, eps[1], eps) == (False, False)


def test_pipeline_runs_on_a_show_with_no_continuity_notes(labelled, tmp_path):
    eps = _eps_without_notes(labelled)
    from promoforge.ingestion import IngestResult
    ing = IngestResult(episodes=eps, warnings=[], files_seen=len(eps), files_skipped=[])
    res = run_pipeline(ingest=ing, settings=Settings(provider="none"))
    assert res.promos and all(p.validation.ok for p in res.promos)
    for p in res.promos:
        if p.kind == "cross_episode":
            assert any("ASSUMPTION" in w for w in res.report["warnings"])


# ---------------------------------------------------------------- quality floor and scoring

def test_quality_floor_is_bounded_and_relative():
    assert quality_floor(0.95) == DEFAULT.quality_min_total
    assert quality_floor(0.5) == 0.60                      # weak story: floor never drops below 0.60
    assert 0.60 <= quality_floor(0.75) <= DEFAULT.quality_min_total


def test_weights_cover_ten_dimensions_and_sum_to_one():
    assert len(WEIGHTS) == 10 and abs(sum(WEIGHTS.values()) - 1) < 1e-9


def test_every_listed_promo_clears_the_quality_rules(labelled):
    res = run_pipeline(ingest=_ing(labelled), settings=Settings(provider="none"))
    floor = quality_floor(max(p.scores.total for p in res.promos))
    for p in res.promos:
        assert p.scores.total >= floor - 1e-9 or len(res.promos) <= DEFAULT.quality_min_keep
        assert p.scores.hook >= DEFAULT.quality_min_hook - 1e-9 or len(res.promos) <= DEFAULT.quality_min_keep


def _ing(eps):
    from promoforge.ingestion import IngestResult
    return IngestResult(episodes=eps, warnings=[], files_seen=len(eps), files_skipped=[])


def _inline_episode(lines, n=1):
    text = "\n".join(f"[{_t(a)} - {_t(b)}] {l}" for a, b, l in lines)
    return parse_episode(f"# Episode {n}\nLogline: test\nContinuity: First.\n\n" + text, f"ep{n}.md")


def _t(x):
    return f"{int(x // 60):02d}:{x - 60 * int(x // 60):05.2f}"


def test_ending_with_goodbye_scores_lower_on_spoiler_and_cliffhanger_than_open_ending():
    base = [(0, 3, "MARA: You forged my name! Give me the contract!"),
            (3, 6, "DEV: You have no proof."),
            (6, 10, "MARA: I have the bank record. I am telling everyone tonight."),
            (10, 14, "DEV: Then you will not leave this room alive."),
            (14, 18, "MARA: Try it. The whole board is outside."),
            (18, 22, "DEV: Who told you about the board?"),
            (22, 26, "MARA: Someone you trusted.")]
    open_end = base + [(26, 30, "DEV: Who? Answer me! Who betrayed me?")]
    closed = base + [(26, 30, "DEV: Fine. It is over. Thank you, goodbye, we are finished here.")]
    eo, ec = _inline_episode(open_end), _inline_episode(closed)
    for e in (eo, ec):
        e.duration = max(e.duration, 31.0)
    ctx = compute_context([eo])
    so = score_segments([(1, 0.0, 30.0)], {1: eo}, ctx)
    ctx2 = compute_context([ec])
    sc = score_segments([(1, 0.0, 30.0)], {1: ec}, ctx2)
    assert so is not None and sc is not None
    assert so.scores.cliffhanger > sc.scores.cliffhanger
    assert so.scores.spoiler >= sc.scores.spoiler


def test_every_promo_has_all_ten_scores_between_0_and_1(labelled):
    res = run_pipeline(ingest=_ing(labelled), settings=Settings(provider="none"))
    for p in res.promos:
        for d in WEIGHTS:
            assert 0.0 <= getattr(p.scores, d) <= 1.0


# ---------------------------------------------------------------- AI: prompt

@pytest.fixture()
def promos_and_ctx(labelled):
    ctx = compute_context(labelled)
    emap = {e.number: e for e in labelled}
    cands, _ = generate_candidates(labelled, ctx)
    return [candidate_to_promo(c, emap) for c in mmr_select(cands, 12)], ctx, emap, cands


def _many(promos, n):
    """The small sample story has few distinct clips; copy them under new ids to reach n (for scoring-maths tests)."""
    out = []
    for i in range(n):
        c = promos[i % len(promos)].model_copy(deep=True)
        c.promo_id = f"{c.promo_id}_c{i}"
        out.append(c)
    return out


def test_rubric_prompt_names_every_editor_criterion_and_treats_script_as_data():
    for word in ("HOOK", "CLIFFHANGER", "COHERENCE", "EMOTION", "CURIOSITY", "ESCALATION", "APPEAL", "SPOILER", "AFTER THE CUT"):
        assert word in JUDGE_SYSTEM
    assert "never instructions" in JUDGE_SYSTEM


def test_prompt_shows_lines_after_the_cut_without_beat_ids(promos_and_ctx):
    promos, ctx, emap, _ = promos_and_ctx
    text = build_prompt(promos[:4], "Premise: test.", emap)
    after = [l for l in text.splitlines() if l.startswith("AFTER THE CUT")]
    assert after and all("E" not in l.split("|")[0].replace("AFTER THE CUT", "") for l in after)
    assert "episode 1 of" in text


def test_prompt_never_asks_the_model_for_timestamps(promos_and_ctx):
    promos, ctx, emap, _ = promos_and_ctx
    text = build_prompt(promos[:2], "", emap)
    assert "timestamp" not in text.lower() or "never" in text.lower()


# ---------------------------------------------------------------- AI: blending

def test_ai_scores_are_rescaled_and_rank_bonus_applied(promos_and_ctx, tmp_path):
    promos, ctx, emap, _ = promos_and_ctx
    client, _ = _client(tmp_path)
    out, rep = judge_promos(client, _many(promos, 12), emap, ctx, "x")
    assert rep["judged"] == 12
    assert 12 >= MIN_RESCALE
    assert rep.get("rescaled_dimensions")
    assert all(p.scoring_mode == "llm+heuristic" for p in out)
    assert all(0.0 <= p.scores.total <= 1.0 for p in out)
    # the model's raw numbers are kept untouched in llm_scores
    assert all(p.llm_scores is not None and p.llm_scores.curiosity > 0 for p in out)


def test_rank_bonus_needs_a_clean_ranking():
    class P:  # minimal stand-in
        def __init__(self, i): self.promo_id = f"p{i}"
    ps = [P(i) for i in range(4)]
    good = [(p, {}, {"rank": i + 1}, 0) for i, p in enumerate(ps)]
    b = _batch_ranks(good)
    assert b["p0"] > 0 > b["p3"] and abs(b["p0"] + b["p3"]) < 1e-9
    dup = [(p, {}, {"rank": 1}, 0) for p in ps]
    assert _batch_ranks(dup) == {}
    junk = [(p, {}, {"rank": "first"}, 0) for p in ps]
    assert _batch_ranks(junk) == {}


def test_identical_ai_scores_for_a_dimension_fall_back_to_rules(promos_and_ctx):
    promos, ctx, emap, _ = promos_and_ctx
    pending = [(p, {"hook": 0.8, "cliffhanger": 0.5 + i * 0.03, "standalone": 0.5, "emotion": 0.5, "coherence": 0.5, "appeal": 0.5},
                {}, 0) for i, p in enumerate(_many(promos, 10))]
    rep = {"warnings": []}
    plan = _rescale(pending, rep)
    assert plan["hook"][0] == "flat" and plan["cliffhanger"][0] == "scale"
    assert any("'hook'" in w for w in rep["warnings"])


# ---------------------------------------------------------------- AI: moment scan

def test_call_plan_stays_inside_the_budget():
    p = plan_calls(30, 50)
    assert p["scan_calls"] == 10 and p["judge_calls"] == 16 and 1 + p["scan_calls"] + p["judge_calls"] + p["slack"] == 30
    small = plan_calls(30, 4)
    assert small["scan_calls"] == 1
    tiny = plan_calls(6, 50)
    assert tiny["scan_calls"] == 0
    assert plan_calls(0, 10)["judge_calls"] == 0


def test_scan_accepts_valid_moments_and_dedupes_against_rule_picks(labelled, tmp_path):
    ctx = compute_context(labelled)
    emap = {e.number: e for e in labelled}
    cands, _ = generate_candidates(labelled, ctx)
    client, _ = _client(tmp_path)
    new, agreed, rep = scan_episodes(client, labelled, emap, ctx, [], "", 5)
    assert rep["episodes_scanned"] == len(labelled) and rep["calls"] >= 1
    for c in new:
        assert 20 - 1e-6 <= c.duration <= 60 + 1e-6
    # same scan against a pool that already holds those windows: they count as agreement, not new clips
    new2, agreed2, rep2 = scan_episodes(client, labelled, emap, ctx, cands, "", 5)
    assert rep2["agreed_with_rules"] >= len(agreed) and len(new2) <= len(new)


class _BadScan(Provider):
    name = "mock"

    def generate(self, system, prompt):
        eps = [int(x) for x in __import__("re").findall(r"(?m)^### EPISODE (\d+)", prompt)]
        data = {"episodes": [{"episode": e, "moments": [
            {"start_beat_id": "E999-S01-B001", "end_beat_id": "NOPE", "why": "x"}]} for e in eps]}
        return Completion(json.dumps(data), 10, 10, "bad")


def test_scan_rejects_made_up_beat_ids(labelled, tmp_path):
    ctx = compute_context(labelled)
    emap = {e.number: e for e in labelled}
    s = Settings(provider="mock", cache_dir=str(tmp_path / "c"), rpm=6000, max_calls=50)
    client = LLMClient(s, provider=_BadScan(s), sleep=lambda x: None)
    new, agreed, rep = scan_episodes(client, labelled, emap, ctx, [], "", 5)
    assert new == [] and rep["rejected"]["bad_id"] == rep["proposed"] > 0


def test_scan_failure_does_not_break_the_run(labelled, tmp_path):
    ctx = compute_context(labelled)
    emap = {e.number: e for e in labelled}
    client, _ = _client(tmp_path, mode="quota")
    new, agreed, rep = scan_episodes(client, labelled, emap, ctx, [], "", 5)
    assert new == [] and rep["error_kinds"] == ["quota"] and rep["warnings"]


# ---------------------------------------------------------------- AI: whole run

def test_full_ai_run_respects_call_budget_and_validates(labelled, tmp_path):
    s = Settings(provider="mock", model="mock-ok", cache_dir=str(tmp_path / "c"), rpm=6000, max_calls=12)
    res = run_pipeline(ingest=_ing(labelled), settings=s, out_dir=tmp_path / "out")
    r = res.report
    assert r["llm"]["calls_made"] <= 12
    assert r["call_plan"]["scan_calls"] + r["call_plan"]["judge_calls"] + 1 + r["call_plan"]["slack"] <= 12
    assert res.promos and all(p.validation.ok for p in res.promos)
    assert {p.source for p in res.promos} <= {"rules", "rules+ai_scan", "ai_scan"}
    exported = json.loads((tmp_path / "out" / "promos.json").read_text(encoding="utf-8"))
    assert "found_by" in json.dumps(exported)


# ---------------------------------------------------------------- must-pass gates

def test_a_spoiler_cannot_hide_behind_a_high_average(promos_and_ctx):
    from promoforge.ranking import apply_gates, gate_penalty
    promos, ctx, emap, _ = promos_and_ctx
    good, spoiler = _many(promos, 2)
    for p in (good, spoiler):
        for d in ("hook", "cliffhanger", "standalone", "spoiler"):
            setattr(p.scores, d, 0.9)
        p.scores.total = 0.88
    spoiler.scores.spoiler = 0.0
    assert gate_penalty(good.scores) == 0
    assert gate_penalty(spoiler.scores) == pytest.approx(0.30)
    assert apply_gates([good, spoiler]) == 1
    assert good.scores.total == 0.88 and spoiler.scores.total == pytest.approx(0.58)
    assert any("must-pass" in n for n in spoiler.notes)
