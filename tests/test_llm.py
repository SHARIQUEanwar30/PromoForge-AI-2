import json
import time

import pytest

from promoforge.candidate_generator import generate_candidates
from promoforge.llm_judge import build_prompt, judge_promos
from promoforge.llm_provider import (GeminiProvider, LLMClient, LLMError, MockProvider, Settings, extract_json,
                                     load_settings, make_provider, parse_env_file)
from promoforge.ranking import candidate_to_promo, mmr_select
from promoforge.story_engine import heuristic_story, llm_story


def _client(tmp_path, mode="ok", **kw):
    s = Settings(provider="mock", model=f"mock-{mode}", cache_dir=str(tmp_path / "cache"), rpm=6000, **kw)
    return LLMClient(s, sleep=lambda x: None), s


@pytest.fixture()
def promos(labelled, ctx_and_map):
    ctx, emap = ctx_and_map
    cands, _ = generate_candidates(labelled, ctx)
    return [candidate_to_promo(c, emap) for c in mmr_select(cands, 8)]


# ---------------------------------------------------------------- settings / .env

def test_env_file_parsing_bom_quotes_empty(tmp_path):
    f = tmp_path / ".env"
    f.write_bytes("﻿PROMOFORGE_PROVIDER=\"gemini\"\nPROMOFORGE_API_KEY='abc123456789'\nPROMOFORGE_MODEL=\n# comment\n".encode("utf-8"))
    d = parse_env_file(f)
    assert d == {"PROMOFORGE_PROVIDER": "gemini", "PROMOFORGE_API_KEY": "abc123456789"}   # BOM + quotes stripped, empty ignored
    s = load_settings(f)
    assert s.provider == "gemini" and s.model == "" and s.masked_key().startswith("abc1") and "6789" not in s.masked_key()


def test_env_example_has_empty_model_and_no_key():
    from pathlib import Path
    txt = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
    assert "PROMOFORGE_MODEL=\n" in txt or txt.rstrip().endswith("PROMOFORGE_MODEL=") or "PROMOFORGE_MODEL=\r\n" in txt
    for line in txt.splitlines():
        if line.startswith("PROMOFORGE_API_KEY"):
            assert line.strip() == "PROMOFORGE_API_KEY="


def test_make_provider_unknown_and_none():
    assert make_provider(Settings(provider="none")) is None
    with pytest.raises(LLMError):
        make_provider(Settings(provider="nonsense"))


def test_extract_json_handles_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('blah {"a": 2} blah') == {"a": 2}


# ---------------------------------------------------------------- client: cache, budget, repair

def test_disk_cache_avoids_second_call(tmp_path):
    c, _ = _client(tmp_path)
    prompt = "TASK: story\nE1: a | continuity: b\n"
    c.complete_json("story", "sys", prompt, ("premise",))
    assert c.calls == 1
    c2, _ = _client(tmp_path)
    c2.complete_json("story", "sys", prompt, ("premise",))
    assert c2.calls == 0 and c2.cache_hits == 1


def test_call_budget_enforced(tmp_path):
    c, _ = _client(tmp_path, max_calls=1)
    c.complete_json("story", "s", "TASK: story\nE1: a | continuity: b\n", ("premise",))
    with pytest.raises(LLMError) as e:
        c.complete_json("story", "s", "TASK: story\nE2: different | continuity: b\n", ("premise",))
    assert e.value.kind == "budget"


def test_bad_json_gets_one_repair_retry(tmp_path):
    c, _ = _client(tmp_path, "bad_json")
    d = c.complete_json("story", "s", "TASK: story\nE1: a | continuity: b\n", ("premise",))
    assert "premise" in d and c.calls == 2                 # first reply broken, repair worked


def test_persistent_bad_json_raises(tmp_path):
    class Broken(MockProvider):
        def generate(self, system, prompt):
            from promoforge.llm_provider import Completion
            return Completion("still not json", 1, 1, "x")
    s = Settings(provider="mock", cache_dir=str(tmp_path / "c"), rpm=6000)
    c = LLMClient(s, provider=Broken(s), sleep=lambda x: None)
    with pytest.raises(LLMError) as e:
        c.complete_json("t", "s", "p", ("a",))
    assert e.value.kind == "bad_json" and c.calls == 2


def test_rate_limit_sleeps_between_calls(tmp_path):
    sleeps = []
    s = Settings(provider="mock", cache_dir=str(tmp_path / "c"), rpm=6)       # 10 s apart
    c = LLMClient(s, sleep=sleeps.append)
    c.complete_json("t", "s", "TASK: story\nE1: x | continuity: y\n", ("premise",))
    c.complete_json("t", "s", "TASK: story\nE2: x | continuity: y\n", ("premise",))
    assert sleeps and sleeps[-1] > 5


def test_token_counting(tmp_path):
    c, _ = _client(tmp_path)
    c.complete_json("story", "s", "TASK: story\nE1: a | continuity: b\n", ("premise",))
    sm = c.summary()
    assert sm["input_tokens_approx"] > 0 and sm["output_tokens_approx"] > 0 and sm["provider"] == "mock"


# ---------------------------------------------------------------- Gemini: model discovery and automatic fallback

def test_gemini_switches_model_on_404_and_records_it():
    calls = []

    def fake_http(url, headers, body, timeout, method="POST"):
        calls.append(url)
        if url.endswith("/models?pageSize=200"):
            return 200, json.dumps({"models": [
                {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": ["generateContent"]}]})
        if "gemini-3.5-flash-lite:generateContent" in url:
            return 404, json.dumps({"error": {"message": "This model models/gemini-3.5-flash-lite is no longer available to new users."}})
        return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3}})

    s = Settings(provider="gemini", api_key="KEY123456789", model="gemini-3.5-flash-lite")
    p = GeminiProvider(s, fake_http)
    out = p.generate("sys", "prompt")
    assert out.model == "gemini-3.1-flash-lite" and p.model == "gemini-3.1-flash-lite"
    assert any("not available" in e for e in p.events) and any("switched" in e for e in p.events)


def test_gemini_empty_model_discovers_and_uses_available():
    def fake_http(url, headers, body, timeout, method="POST"):
        if url.endswith("pageSize=200"):
            return 200, json.dumps({"models": [{"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]}]})
        assert "gemini-3.6-flash:generateContent" in url
        return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    p = GeminiProvider(Settings(provider="gemini", api_key="KEY123456789"), fake_http)
    assert p.generate("s", "p").model == "gemini-3.6-flash"


def test_gemini_bad_key_is_clear():
    def fake_http(url, headers, body, timeout, method="POST"):
        return 400, json.dumps({"error": {"message": "API key not valid. Please pass a valid API key."}})
    with pytest.raises(LLMError) as e:
        GeminiProvider(Settings(provider="gemini", api_key="bad"), fake_http).generate("s", "p")
    assert e.value.kind == "auth"


def test_gemini_never_sends_key_in_url():
    seen = []

    def fake_http(url, headers, body, timeout, method="POST"):
        seen.append((url, headers))
        if url.endswith("pageSize=200"):
            return 200, json.dumps({"models": []})
        return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    GeminiProvider(Settings(provider="gemini", api_key="SECRETKEY12345"), fake_http).generate("s", "p")
    assert all("SECRETKEY12345" not in u for u, _ in seen)


# ---------------------------------------------------------------- story engine

def test_story_llm_and_heuristic(labelled, ctx_and_map, tmp_path):
    ctx, _ = ctx_and_map
    h = heuristic_story(labelled, ctx)
    assert h["mode"] == "heuristic" and h["main_characters"]
    c, _ = _client(tmp_path)
    s = llm_story(c, labelled, h)
    assert s["mode"] == "llm" and s["major_reveals"] and all(r["episode"] in {e.number for e in labelled} for r in s["major_reveals"])


def test_story_llm_failure_falls_back(labelled, ctx_and_map, tmp_path):
    ctx, _ = ctx_and_map
    c, _ = _client(tmp_path, max_calls=0)
    s = llm_story(c, labelled, heuristic_story(labelled, ctx))
    assert s["mode"] == "heuristic" and any("failed" in n for n in s["notes"])


# ---------------------------------------------------------------- judge: beat ids only, Python re-validates

def test_prompt_contains_beat_ids_not_timestamps_to_edit(promos):
    pr = build_prompt(promos[:2], "story")
    assert "E001-S01-B" in pr or "E00" in pr
    assert "start_beat_id" in pr and "SHORTEN" in pr


def test_judge_blends_scores_and_marks_mode(promos, ctx_and_map, tmp_path):
    ctx, emap = ctx_and_map
    c, _ = _client(tmp_path)
    out, rep = judge_promos(c, promos, emap, ctx)
    assert rep["judged"] == len(promos) and rep["failed_batches"] == 0
    for before, after in zip(promos, out):
        assert after.scoring_mode == "llm+heuristic" and after.llm_scores and after.heuristic_scores
        expect = 0.7 * after.llm_scores.hook + 0.3 * after.heuristic_scores.hook
        assert abs(after.scores.hook - round(expect, 3)) < 0.002
        assert after.validation.ok


def test_judge_trim_is_revalidated_and_only_shortens(promos, ctx_and_map, tmp_path):
    ctx, emap = ctx_and_map
    c, _ = _client(tmp_path, "trim")
    out, rep = judge_promos(c, promos, emap, ctx)
    for before, after in zip(promos, out):
        for b, a in zip(before.segments, after.segments):
            assert a.start >= b.start - 0.06 and a.end <= b.end + 0.06       # never extends
        assert after.validation.ok                                           # never produces an invalid clip
        assert 20 - 0.06 <= after.duration <= 60 + 0.06
    assert rep["trims_applied"] + rep["trims_rejected"] > 0


def test_judge_ignores_unknown_beat_ids(promos, ctx_and_map, tmp_path):
    ctx, emap = ctx_and_map
    c, _ = _client(tmp_path, "bad_ids")
    out, rep = judge_promos(c, promos, emap, ctx)
    assert rep["bad_ids_ignored"] > 0
    for before, after in zip(promos, out):
        assert [(s.start, s.end) for s in before.segments] == [(s.start, s.end) for s in after.segments]
        assert after.hook == before.hook                                       # heuristic hook text kept


def test_judge_removes_invented_quotes(promos, ctx_and_map, tmp_path):
    ctx, emap = ctx_and_map
    c, _ = _client(tmp_path, "fake_quote")
    out, rep = judge_promos(c, promos, emap, ctx)
    assert rep["quotes_removed"] > 0
    assert all("never spoken anywhere" not in p.why for p in out)


def test_judge_falls_back_when_llm_dies(promos, ctx_and_map, tmp_path):
    ctx, emap = ctx_and_map
    c, _ = _client(tmp_path, max_calls=0)
    out, rep = judge_promos(c, promos, emap, ctx)
    assert rep["judged"] == 0 and rep["failed_batches"] >= 1 and rep["warnings"]
    assert all(p.scoring_mode == "heuristic" and p.llm_scores is None for p in out)
    assert any("heuristic scores" in n for n in out[0].notes)


def test_gemini_key_never_in_cache_or_outputs(tmp_path, labelled):
    from promoforge.pipeline import run_pipeline
    s = Settings(provider="mock", api_key="SUPERSECRETKEY99", cache_dir=str(tmp_path / "cache"), rpm=6000)
    run_pipeline(ingest=type("I", (), {"episodes": labelled, "warnings": [], "files_seen": 4, "files_skipped": 0})(),
                 out_dir=tmp_path / "out", settings=s, top_n=5)
    for f in [x for x in list((tmp_path / "out").rglob("*")) + list((tmp_path / "cache").rglob("*")) if x.is_file()]:
        assert "SUPERSECRETKEY99" not in f.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------- paid providers: model chosen automatically (no model box in the UI)

def test_openai_compatible_picks_a_cheap_recent_chat_model_when_model_is_empty():
    from promoforge.llm_provider import OpenAICompatProvider
    seen = {}

    def fake_http(url, headers, body, timeout, method="POST"):
        if url.endswith("/models"):
            return 200, json.dumps({"data": [
                {"id": "text-embedding-3-small", "created": 5}, {"id": "gpt-4o", "created": 10},
                {"id": "gpt-4o-mini-2024-07-18", "created": 20}, {"id": "gpt-4o-mini", "created": 15},
                {"id": "gpt-4o-audio-preview", "created": 30}]})
        seen["model"] = body["model"]
        return 200, json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {}})
    p = OpenAICompatProvider(Settings(provider="openai", api_key="KEY123456789"), fake_http)
    p.generate("s", "p")
    assert seen["model"] == "gpt-4o-mini" and any("chosen automatically" in e for e in p.events)


def test_anthropic_picks_haiku_before_sonnet_when_model_is_empty():
    from promoforge.llm_provider import AnthropicProvider
    seen = {}

    def fake_http(url, headers, body, timeout, method="POST"):
        if url.endswith("/v1/models"):
            return 200, json.dumps({"data": [{"id": "claude-sonnet-x", "created_at": "2026-05-01T00:00:00Z"},
                                             {"id": "claude-haiku-old", "created_at": "2025-01-01T00:00:00Z"},
                                             {"id": "claude-haiku-new", "created_at": "2026-02-01T00:00:00Z"}]})
        seen["model"] = body["model"]
        return 200, json.dumps({"content": [{"type": "text", "text": "{}"}], "usage": {}})
    AnthropicProvider(Settings(provider="anthropic", api_key="KEY123456789"), fake_http).generate("s", "p")
    assert seen["model"] == "claude-haiku-new"


def test_paid_provider_with_bad_key_gives_auth_error_not_a_crash():
    from promoforge.llm_provider import OpenAICompatProvider
    def fake_http(url, headers, body, timeout, method="POST"):
        return 401, json.dumps({"error": {"message": "Incorrect API key provided"}})
    with pytest.raises(LLMError) as e:
        OpenAICompatProvider(Settings(provider="openai", api_key="bad"), fake_http).generate("s", "p")
    assert e.value.kind == "auth"


# ---------------------------------------------------------------- free-limit reached: the UI needs to know

def test_quota_mode_is_reported_as_ai_issue(sample_dirs, tmp_path):
    from promoforge.pipeline import run_pipeline
    s = Settings(provider="mock", model="mock-quota", cache_dir=str(tmp_path / "c"), rpm=6000)
    res = run_pipeline(input_path=sample_dirs["story_labelled"], settings=s, top_n=5)
    assert res.report["ai"]["status"] == "failed" and res.report["ai"]["issue"] == "quota"
    assert res.promos and all(p.validation.ok for p in res.promos)          # still a full rule-based result


def test_quota_late_gives_partial_ai_result_and_still_valid_promos(sample_dirs, tmp_path):
    from promoforge.pipeline import run_pipeline
    s = Settings(provider="mock", model="mock-quota_late", cache_dir=str(tmp_path / "c"), rpm=6000)
    res = run_pipeline(input_path=sample_dirs["story_labelled"], settings=s, top_n=5)
    assert res.report["ai"]["issue"] == "quota" and res.report["ai"]["status"] in ("partial", "failed")
    assert all(p.validation.ok for p in res.promos)


def test_ai_status_ok_and_off(sample_dirs, tmp_path):
    from promoforge.pipeline import run_pipeline
    ok = run_pipeline(input_path=sample_dirs["story_labelled"],
                      settings=Settings(provider="mock", cache_dir=str(tmp_path / "c"), rpm=6000), top_n=5)
    assert ok.report["ai"] == {"status": "ok", "issue": None}
    off = run_pipeline(input_path=sample_dirs["story_labelled"], settings=Settings(provider="none"), top_n=5)
    assert off.report["ai"] == {"status": "off", "issue": None}
