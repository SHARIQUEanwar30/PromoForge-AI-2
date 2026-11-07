"""Tests for the helpers behind the simple screen (no Streamlit needed)."""
import time

import pytest

import ui_config as C
import ui_logic as L


def test_provider_table_is_sane_and_easy_to_extend():
    ids = [p["id"] for p in C.PROVIDERS]
    assert len(ids) == len(set(ids)) and C.DEFAULT_PROVIDER in ids
    assert C.PROVIDERS[0]["provider"] == "none" and C.PROVIDERS[0]["label"] == "Rule-based"
    for p in C.PROVIDERS:
        assert set(("id", "label", "provider", "free", "site_key", "blurb")) <= set(p)
        if p["provider"] != "none":
            assert p.get("key_url", "").startswith("https://") and p.get("company")
        if not p["free"]:
            assert p["site_key"] is False            # the site's private key is never used for a paid AI


def test_every_page_has_icon_and_short_intro():
    assert len(C.PAGES) == 6 and "Evaluation" not in [p[0] for p in C.PAGES]
    for name, icon, intro in C.PAGES:
        assert icon and 10 < len(intro) < 140


def test_auto_promo_count_scales_but_stays_in_bounds():
    assert L.auto_top_n(50) == 60 and L.auto_top_n(3) == 8 and L.auto_top_n(0) == 8 and L.auto_top_n(1000) == 60
    assert 8 <= L.auto_top_n(12) <= 40


def test_rule_based_needs_no_key():
    s, problem = L.resolve("rules")
    assert s.provider == "none" and problem is None


def test_gemini_uses_the_sites_private_key_so_visitors_type_nothing():
    s, problem = L.resolve("gemini", secrets={"PROMOFORGE_API_KEY": "SITEKEY123456789", "PROMOFORGE_PROVIDER": "gemini"})
    assert problem is None and s.provider == "gemini" and s.api_key == "SITEKEY123456789" and s.model == ""
    assert s.max_calls == C.AUTO["ai_call_budget"]


def test_visitors_own_key_wins_over_the_sites_key():
    s, problem = L.resolve("gemini", "OWNKEY123456789", secrets={"PROMOFORGE_API_KEY": "SITEKEY123456789"})
    assert problem is None and s.api_key == "OWNKEY123456789"


def test_gemini_with_no_key_anywhere_asks_for_a_free_key(monkeypatch, tmp_path):
    monkeypatch.delenv("PROMOFORGE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)                       # no .env here
    s, problem = L.resolve("gemini", secrets={})
    assert problem == "missing"


@pytest.mark.parametrize("pid", ["openai", "claude"])
def test_paid_ai_never_borrows_the_sites_key_and_asks_for_the_visitors(pid):
    s, problem = L.resolve(pid, secrets={"PROMOFORGE_API_KEY": "SITEGEMINIKEY12345", "PROMOFORGE_PROVIDER": "gemini"})
    assert problem == "paid" and s.api_key == ""
    s2, problem2 = L.resolve(pid, "sk-visitor-key-123456")
    assert problem2 is None and s2.api_key == "sk-visitor-key-123456" and s2.model == ""
    assert s2.base_url == next(p for p in C.PROVIDERS if p["id"] == pid).get("base_url", "")


def test_call_budget_can_be_lowered_by_the_site_owner():
    s, _ = L.resolve("gemini", secrets={"PROMOFORGE_API_KEY": "SITEKEY123456789", "PROMOFORGE_MAX_CALLS": "12"})
    assert s.max_calls == 12


def test_site_secrets_reads_getter_then_environment(monkeypatch):
    monkeypatch.setenv("PROMOFORGE_API_KEY", "ENVKEY12345678")
    got = L.site_secrets(lambda n: {"PROMOFORGE_MAX_CALLS": "7"}.get(n))
    assert got["PROMOFORGE_API_KEY"] == "ENVKEY12345678" and got["PROMOFORGE_MAX_CALLS"] == "7"

    def boom(_):
        raise RuntimeError("no secrets file")
    assert L.site_secrets(boom)["PROMOFORGE_API_KEY"] == "ENVKEY12345678"      # a missing secrets file is fine


def test_popup_texts_for_each_reason():
    gem, claude = L.provider_by_id("gemini"), L.provider_by_id("claude")
    paid = L.popup_texts("paid", claude)
    assert "Claude needs your own key" in paid["title"] and "not free" in " ".join(paid["body"])
    assert any("console.anthropic.com" in s for s in paid["steps"])
    quota = L.popup_texts("quota", gem)
    assert "limit" in quota["title"] and "Create API key" in " ".join(quota["steps"])
    assert "India time" in " ".join(quota["body"]) or "Pacific" in " ".join(quota["body"])
    assert "did not work" in L.popup_texts("badkey", gem)["title"]
    assert L.popup_texts("missing", gem)["placeholder"] == "Paste your Gemini key here"


def test_ai_problem_mapping():
    assert L.ai_problem({"ai": {"status": "failed", "issue": "quota"}}) == "quota"
    assert L.ai_problem({"ai": {"status": "partial", "issue": "rate_limit"}}) == "quota"
    assert L.ai_problem({"ai": {"status": "failed", "issue": "auth"}}) == "badkey"
    assert L.ai_problem({"ai": {"status": "failed", "issue": "network"}}) == "failed"
    assert L.ai_problem({"ai": {"status": "ok", "issue": None}}) is None
    assert L.ai_problem({"ai": {"status": "off", "issue": None}}) is None
    assert L.ai_problem({}) is None


def test_reset_time_text_is_a_clock_time_or_plain_words():
    t = L.reset_time_text()
    assert t.endswith("India time") or t == "midnight Pacific time"


def test_fifty_uploaded_files_finish_well_inside_twenty_seconds(sample_dirs):
    """The brief: 50 episodes in one go, and the Run button must not take more than about 20 s (Rule-based)."""
    from promoforge.ingestion import load_bytes_items
    from promoforge.llm_provider import Settings
    from promoforge.pipeline import run_pipeline
    base = sorted(sample_dirs["story_labelled"].glob("*.txt"))
    items = []
    for i in range(50):
        raw = base[i % len(base)].read_text(encoding="utf-8")
        items.append((f"ep-{i + 1:02d}.txt", (raw + f"\n\n(copy {i})\n").encode("utf-8")))
    t0 = time.time()
    ing = load_bytes_items(items)
    res = run_pipeline(ingest=ing, settings=Settings(provider="none"), top_n=L.auto_top_n(len(ing.episodes)))
    took = time.time() - t0
    assert len(ing.episodes) >= 40 and res.promos and all(p.validation.ok for p in res.promos)
    assert took < 20, f"took {took:.1f}s"
