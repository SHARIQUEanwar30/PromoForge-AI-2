"""Headless Streamlit tests (Streamlit AppTest) for the simple editor-friendly UI."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import ui_config as C  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")
SAMPLE1 = "Sample story 1 (timestamps in blocks)"


def _at() -> AppTest:
    return AppTest.from_file(APP, default_timeout=60)


def _goto(at: AppTest, page: str):
    at.session_state["page_choice"] = page
    at.run()


def _text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def _loaded() -> AppTest:
    at = _at().run()
    assert not at.exception
    at.selectbox(key="sample_pick").set_value(SAMPLE1).run()
    at.button(key="run_btn").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["res"] is not None
    return at


# ---------------------------------------------------------------- first page

def test_first_page_has_project_name_and_plain_description_and_no_technical_boxes():
    at = _at().run()
    assert not at.exception
    t = _text(at)
    assert C.APP_NAME in t and "ranks them from best to worst" in t
    assert at.session_state["page_choice"] == "Upload & Analyze"
    assert len(at.text_input) == 0                       # no Model / API key / Base URL / saved-run boxes
    assert len(at.number_input) == 0 and len(at.slider) == 0   # promo count and call budget are automatic
    for word in ("saved run", "Base URL", "Model", "budget", "heuristic", "None"):
        assert word not in t


def test_ai_dropdown_lists_rule_based_first_and_never_says_none():
    at = _at().run()
    opts = at.selectbox(key="ai_choice").options
    assert "Rule-based" in opts[0] and "Gemini" in opts[1]
    assert any("OpenAI" in o for o in opts) and any("Claude" in o for o in opts)
    assert not any("none" in o.lower() for o in opts)


def test_six_pages_with_one_editing_desk_and_no_evaluation_page():
    at = _at().run()
    pages = at.radio(key="page_choice").options
    assert len(pages) == 6 and not any("Evaluation" in x for x in pages) and pages[1].endswith("Dashboard")
    assert any(x.endswith("Editing Desk") for x in pages)
    assert not any("Candidate Inspection" in x or "Editorial Review" in x for x in pages)


def test_run_without_files_or_sample_asks_politely():
    at = _at().run()
    at.button(key="run_btn").click().run()
    assert not at.exception
    assert any("Add your episodes first" in w.value for w in at.warning)
    assert "res" not in at.session_state or at.session_state["res"] is None


def test_sample_run_lands_on_dashboard_in_rule_based_mode():
    at = _loaded()
    assert at.session_state["page_choice"] == "Dashboard"
    res = at.session_state["res"]
    assert len(res.promos) >= 4 and res.report["mode"].startswith("rules-only")
    t = _text(at)
    assert "What's here" in t and "Rule-based" in t and "Top picks" in t


# ---------------------------------------------------------------- every page

def test_every_page_renders_and_opens_with_a_whats_here_line():
    at = _loaded()
    for name, _icon, intro in C.PAGES[1:]:
        _goto(at, name)
        assert not at.exception, f"{name}: {[e.value for e in at.exception]}"
        t = _text(at)
        assert "What's here" in t and intro.split(":")[0][:25] in t, name


def test_pages_before_a_run_show_a_friendly_empty_state():
    at = _at().run()
    for name in ("Dashboard", "Promo Discovery", "Export"):
        _goto(at, name)
        assert not at.exception
        assert "Nothing to show yet" in _text(at)


def test_promo_cards_use_plain_language():
    at = _loaded()
    _goto(at, "Promo Discovery")
    t = _text(at)
    assert "Hook" in t and "Cliffhanger" in t and "Why it works" in t
    assert "Opens with" not in t and "Cuts on" not in t
    assert any(w in t for w in ("Strong pick", "Good pick", "Double-check"))
    assert "heuristic" not in t.lower() and "scores: " not in t


def test_promo_cards_have_no_keep_skip_buttons_but_the_editing_desk_does():
    at = _loaded()
    _goto(at, "Promo Discovery")
    keys = {b.key for b in at.button}
    assert not any(str(k).startswith(("keep_", "skip_")) for k in keys)
    _goto(at, "Editing Desk")
    assert {"rv_ok", "rv_no", "rv_flag", "rv_clear"} <= {b.key for b in at.button}


def test_editing_desk_keep_then_export_has_the_decision():
    at = _loaded()
    _goto(at, "Editing Desk")
    at.button(key="rv_ok").click().run()
    assert not at.exception
    assert list(at.session_state["reviews"].values())[0]["status"] == "approved"
    _goto(at, "Export")
    assert not at.exception and len(at.get("download_button")) >= 2


def _first_single(at):
    pid = at.session_state["desk_pick"]
    p = next(p for p in at.session_state["res"].promos if p.promo_id == pid)
    assert len(p.segments) == 1
    return pid, p


def test_editing_desk_plus_and_minus_move_the_cut_and_save_it():
    at = _loaded()
    _goto(at, "Editing Desk")
    pid, p = _first_single(at)
    at.button(key=f"end_m_{pid}").click().run()          # end 0.5 s earlier (or on to the next clean cut)
    assert not at.exception, [e.value for e in at.exception]
    edit = at.session_state["reviews"].get(pid, {}).get("edit")
    msg = at.session_state["desk_msg"]
    if msg["ok"]:
        assert edit is not None and edit["end"] < p.segments[0].end
        assert any("saved" in s.value for s in at.success)
    else:                                                  # a refused move changes nothing and says why
        assert edit is None and any("Not changed" in e.value for e in at.error)


def test_editing_desk_refuses_a_clip_shorter_than_20_seconds_in_plain_words():
    at = _loaded()
    _goto(at, "Editing Desk")
    pid, p = _first_single(at)
    at.number_input(key=f"de_{pid}").set_value(p.segments[0].start + 10.0).run()
    assert any("Not changed" in e.value and "between 20 and 60 seconds" in e.value for e in at.error)
    assert "edit" not in at.session_state["reviews"].get(pid, {})
    assert at.number_input(key=f"de_{pid}").value == pytest.approx(p.segments[0].end)     # the box went back


def test_editing_desk_clear_removes_only_the_decision():
    at = _loaded()
    _goto(at, "Editing Desk")
    at.button(key="rv_no").click().run()
    assert list(at.session_state["reviews"].values())[0]["status"] == "rejected"
    at.button(key="rv_clear").click().run()
    assert not at.exception and at.session_state["reviews"] == {}


def test_export_without_any_decision_still_offers_everything():
    at = _loaded()
    _goto(at, "Export")
    assert not at.exception
    keys = {b.key for b in at.get("download_button")}
    assert "dl_csv" in keys and ("dl_txt_zip" in keys or any(str(k).startswith("dl_txt_") for k in keys))
    opts = at.radio(key="exp_scope").options                         # "only the ones I kept" appears after a Keep
    assert len(opts) == 1 and opts[0].startswith("All promos")


def test_export_offers_kept_only_after_a_keep():
    at = _loaded()
    _goto(at, "Editing Desk")
    at.button(key="rv_ok").click().run()
    _goto(at, "Export")
    opts = at.radio(key="exp_scope").options
    assert len(opts) == 2 and opts[0].startswith("All promos") and opts[1].startswith("Only the promos I kept (1)")
    at.radio(key="exp_scope").set_value("kept").run()
    assert not at.exception
    assert at.session_state["exp_scope"] == "kept"


# ---------------------------------------------------------------- AI choices and the key pop-up

def test_paid_ai_without_key_does_not_run_and_does_not_crash():
    at = _at().run()
    at.selectbox(key="sample_pick").set_value(SAMPLE1).run()
    at.selectbox(key="ai_choice").set_value("claude").run()
    assert not at.exception
    at.button(key="run_btn").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert "res" not in at.session_state or at.session_state["res"] is None      # nothing ran without a key


def test_gemini_without_any_key_does_not_run_and_does_not_crash(monkeypatch):
    monkeypatch.delenv("PROMOFORGE_API_KEY", raising=False)
    at = _at().run()
    at.selectbox(key="sample_pick").set_value(SAMPLE1).run()
    at.selectbox(key="ai_choice").set_value("gemini").run()
    at.button(key="run_btn").click().run()
    assert not at.exception
    assert "res" not in at.session_state or at.session_state["res"] is None


def test_selection_survives_visiting_another_page():
    at = _loaded()
    _goto(at, "Upload & Analyze")
    assert at.selectbox(key="ai_choice").value == "rules"


def test_free_limit_reached_shows_message_and_own_key_button():
    from promoforge.llm_provider import Settings
    from promoforge.pipeline import run_pipeline
    sample = Path(__file__).resolve().parent.parent / "sample_data" / "story_labelled"
    res = run_pipeline(input_path=sample, settings=Settings(provider="mock", model="mock-quota", rpm=6000), top_n=5)
    at = _at().run()
    at.session_state["res"] = res
    _goto(at, "Dashboard")
    assert not at.exception
    assert any("free AI limit is finished" in w.value for w in at.warning)
    assert at.button(key="dash_ownkey") is not None


def test_dashboard_does_not_show_the_times_double_checked_tile_and_uses_hook_and_cliffhanger():
    at = _loaded()
    t = _text(at)
    assert "Times double-checked" not in t and "Episodes read" in t and "Promos found" in t
    assert "Hook:" in t and "Cliffhanger:" in t and "Opens with" not in t and "ends on" not in t
