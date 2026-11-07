"""PromoForge - the web app.

Run on your laptop:   streamlit run app.py
Change wording, colours, the AI list or the hidden settings in ui_config.py (not here).
A key typed into the pop-up lives only in this browser session's memory. It is never written to disk or to outputs.
"""
from __future__ import annotations

import csv
import html
import io
import json
import runpy
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import ui_config as C  # noqa: E402
import ui_logic as L  # noqa: E402
from promoforge.config import WEIGHTS  # noqa: E402
from promoforge.editing import (STEP, apply_edit, check_edit, decision_of, effective_promos, nudge_time,  # noqa: E402
                                script_view_html)
from promoforge.export_text import promo_text_files, zip_bytes  # noqa: E402
from promoforge.ingestion import load_bytes_items, load_input  # noqa: E402
from promoforge.models import fmt_ts  # noqa: E402
from promoforge.pipeline import CSV_COLUMNS, promo_to_dict, promo_to_row, run_pipeline  # noqa: E402

st.set_page_config(page_title=C.APP_NAME, page_icon=C.APP_ICON, layout="wide")

PAGE_NAMES = [p[0] for p in C.PAGES]
PAGE_META = {n: (i, d) for n, i, d in C.PAGES}
SCORE_LABELS = {"hook": "Opening hook", "cliffhanger": "Cliffhanger", "standalone": "Makes sense alone",
                "emotion": "Emotion", "coherence": "Flow", "appeal": "Appeal", "duration_fit": "Length fit",
                "curiosity": "Curiosity", "escalation": "Rising tension", "spoiler": "Keeps secrets"}
STATUS_TEXT = {"approved": "✅ Kept", "rejected": "🚫 Skipped", "flagged": "🚩 Flagged"}


# ------------------------------------------------------------------ look and feel

def inject_css() -> None:
    c = C.COLORS
    css = f"""
:root{{--bg:{c['bg']};--panel:{c['panel']};--accent:{c['accent']};--accent2:{c['accent2']};--gold:{c['gold']};
--violet:{c['violet']};--text:{c['text']};--muted:{c['muted']};--good:{c['good']};}}
.stApp{{background:radial-gradient(900px 420px at 12% -8%,rgba(255,77,109,.22),transparent 60%),
radial-gradient(800px 400px at 98% 0%,rgba(123,97,255,.25),transparent 60%),var(--bg);}}
.block-container{{max-width:1000px;padding-top:2.2rem;padding-bottom:4rem;}}
[data-testid="stSidebar"]{{background:#14152b;border-right:1px solid rgba(255,255,255,.08);}}
[data-testid="stHeader"]{{background:transparent;}}
h1.pf-hero{{font-size:3.3rem;font-weight:800;letter-spacing:-1px;margin:0;line-height:1.1;}}
.pf-grad{{background:linear-gradient(90deg,var(--accent),var(--accent2) 55%,var(--gold));-webkit-background-clip:text;
background-clip:text;color:transparent !important;-webkit-text-fill-color:transparent !important;}}
.pf-sub{{font-size:1.18rem;line-height:1.55;color:#cfd0e6;margin:.7rem 0 1.4rem;max-width:760px;}}
.pf-steps{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:1.2rem;}}
.pf-step{{display:flex;align-items:center;gap:9px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);
border-radius:999px;padding:7px 15px 7px 7px;font-size:.95rem;}}
.pf-step b{{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-size:.85rem;color:#fff;
background:linear-gradient(135deg,var(--accent),var(--accent2));}}
.pf-label{{font-size:1.02rem;font-weight:700;margin:.1rem 0 .5rem;}}
.pf-ph{{display:flex;align-items:center;gap:12px;}} .pf-ph .ico{{font-size:2rem;}}
.pf-ph h1{{margin:0;padding:0;font-size:2.5rem;font-weight:800;letter-spacing:-.5px;}}
.pf-intro{{display:flex;gap:10px;align-items:flex-start;background:rgba(123,97,255,.14);border:1px solid rgba(123,97,255,.42);
border-radius:14px;padding:12px 16px;font-size:1.02rem;color:#e4e4f8;margin:.7rem 0 1.3rem;}}
.pf-tiles{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:1.2rem;}}
@media(max-width:700px){{.pf-tiles{{grid-template-columns:repeat(2,1fr);}} h1.pf-hero{{font-size:2.4rem;}}}}
.pf-tile{{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.11);border-radius:16px;padding:14px 16px;}}
.pf-tile .n{{font-size:2rem;font-weight:800;line-height:1.15;}} .pf-tile .t{{color:var(--muted);font-size:.88rem;}}
.pf-prow{{display:flex;align-items:center;gap:14px;padding:12px 2px;border-top:1px solid rgba(255,255,255,.08);}}
.pf-prow.first{{border-top:0;}}
.pf-rank{{min-width:40px;height:40px;border-radius:50%;display:grid;place-items:center;font-weight:800;color:#fff;
background:linear-gradient(135deg,var(--accent),var(--accent2));}}
.pf-pm{{flex:1;min-width:0;}} .pf-pm .a{{font-weight:700;font-size:1.02rem;}}
.pf-pm .b{{color:var(--muted);font-size:.9rem;margin-top:2px;}}
.pf-sc{{font-size:1.4rem;font-weight:800;color:var(--gold);}}
.pf-pill{{display:inline-block;font-size:.78rem;padding:3px 10px;border-radius:999px;margin-right:6px;white-space:nowrap;
background:rgba(255,255,255,.1);color:#d8d9ee;}}
.pf-pill.good{{background:rgba(80,220,140,.16);color:var(--good);}}
.pf-pill.warn{{background:rgba(255,190,70,.16);color:#ffd27a;}}
.pf-tag{{display:inline-block;font-size:.78rem;padding:2px 10px;border-radius:999px;margin:0 6px 4px 0;
background:rgba(123,97,255,.2);color:#cfc6ff;}}
.pf-head{{display:flex;align-items:center;gap:14px;}}
.pf-head .t{{flex:1;min-width:0;}} .pf-head .t b{{font-size:1.15rem;}} .pf-head .t span{{color:var(--muted);font-size:.9rem;}}
.pf-ring{{width:60px;height:60px;border-radius:50%;display:grid;place-items:center;
background:conic-gradient(var(--gold) calc(var(--p)*1%),rgba(255,255,255,.12) 0);}}
.pf-ring b{{width:46px;height:46px;border-radius:50%;background:var(--panel);display:grid;place-items:center;font-size:1.05rem;}}
.pf-q{{border-left:4px solid var(--accent);background:rgba(255,255,255,.05);border-radius:0 12px 12px 0;padding:8px 14px;margin:8px 0;}}
.pf-q small{{display:block;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-size:.7rem;}}
.pf-q.end{{border-left-color:var(--violet);}}
.pf-why{{color:#dcdcf2;margin:8px 0;}}
.pf-bar{{height:8px;border-radius:99px;background:rgba(255,255,255,.1);position:relative;margin:8px 0 2px;}}
.pf-bar i{{position:absolute;top:0;bottom:0;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--accent2));}}
.pf-barcap{{color:var(--muted);font-size:.78rem;}}
.pf-warn{{background:rgba(255,190,70,.1);border:1px solid rgba(255,190,70,.35);color:#ffe2a8;border-radius:10px;padding:7px 12px;
margin:6px 0;font-size:.9rem;}}
.pf-line{{padding:3px 8px;border-radius:6px;font-size:.93rem;}} .pf-line.in{{background:#fff3a3;color:#111;}}
.pf-line code{{background:rgba(0,0,0,.25);color:inherit;padding:0 5px;border-radius:4px;margin-right:6px;font-size:.8rem;}}
.pf-line.in code{{background:rgba(0,0,0,.12);}} .pf-line .cam{{opacity:.6;}}
.pf-note{{color:var(--muted);font-size:.85rem;margin-top:1rem;}}
.pf-empty{{text-align:center;padding:2.2rem 1rem;color:#cfd0e6;}} .pf-empty .big{{font-size:2.6rem;}}
button[data-testid="stBaseButton-primary"],button[kind="primary"]{{background:linear-gradient(90deg,var(--accent),var(--accent2));
border:0;color:#fff;font-weight:800;border-radius:14px;min-height:3rem;box-shadow:0 8px 24px rgba(255,77,109,.28);}}
button[data-testid="stBaseButton-primary"]:hover,button[kind="primary"]:hover{{filter:brightness(1.08);color:#fff;}}
button[data-testid="stBaseButton-primary"],button[kind="primary"]{{width:100%;}}
div[data-testid="stButton"]:has(button[kind="primary"]){{width:100%;}}
.st-key-run_btn,.st-key-run_btn [data-testid="stButton"],.st-key-run_btn button{{width:100% !important;}}
button[data-testid="stBaseButton-primary"] p,button[kind="primary"] p{{font-size:1.2rem;font-weight:800;}}
[data-testid="stFileUploaderDropzone"]{{border:2px dashed #ff6b8a;border-radius:16px;background:rgba(255,77,109,.06);}}
div[data-testid="stVerticalBlockBorderWrapper"]{{border-radius:18px;}}
.st-key-desk_times [data-testid="stNumberInputStepUp"],.st-key-desk_times [data-testid="stNumberInputStepDown"]{{display:none;}}
.st-key-desk_times input{{text-align:center;font-weight:700;}}
"""
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def H(*parts: str) -> str:
    """Join HTML pieces on one line (Markdown treats indented or blank-line-separated HTML as code)."""
    return "".join(parts)


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def page_header(name: str) -> None:
    icon, intro = PAGE_META[name]
    st.markdown(H('<div class="pf-ph"><span class="ico">', icon, '</span><h1><span class="pf-grad">', esc(name), '</span></h1></div>'),
                unsafe_allow_html=True)
    st.markdown(H('<div class="pf-intro"><span>💡</span><span><b>What\'s here:</b> ', esc(intro), '</span></div>'),
                unsafe_allow_html=True)


# ------------------------------------------------------------------ state helpers

def result():
    return st.session_state.get("res")


def reviews() -> dict:
    return st.session_state.setdefault("reviews", {})


def save_reviews() -> None:
    res = result()
    if res is not None and res.out_dir:
        try:
            Path(res.out_dir, "reviews.json").write_text(json.dumps(reviews(), indent=2), encoding="utf-8")
        except OSError:
            pass


def own_keys() -> dict:
    return st.session_state.setdefault("own_keys", {})


def secret_get(name: str):
    try:
        return st.secrets.get(name)
    except Exception:  # noqa: BLE001  (no secrets file: normal on a laptop)
        return ""


def sample_dir(name: str) -> Path:
    d = ROOT / "sample_data" / name
    if not d.exists():
        runpy.run_path(str(ROOT / "tools" / "make_sample_data.py"), run_name="__main__")
    return d


def go_to(page: str) -> None:
    st.session_state["page_choice"] = page


def ask_key(reason: str, pid: str) -> None:
    st.session_state["ask_key"] = (reason, pid)


def need_result() -> bool:
    if result() is None:
        st.markdown(H('<div class="pf-empty"><div class="big">🎬</div><div>Nothing to show yet.</div>',
                      '<div>Add your episodes first, then come back here.</div></div>'), unsafe_allow_html=True)
        st.button("Go to Upload & Analyze", key=f"goto_up_{st.session_state.get('page_choice')}", type="primary",
                  on_click=go_to, args=(C.FIRST_PAGE,))
        return False
    return True


def friendly_warning(w: str) -> str:
    if w.startswith("RULES-ONLY"):
        return ("Rule-based mode: quick and free. The scores come from written rules, so treat them as a guide. "
                "Pick Gemini for a smarter result.")
    return w


# ------------------------------------------------------------------ the "needs a key" pop-up

def open_key_dialog(reason: str, pid: str) -> None:
    p = L.provider_by_id(pid)
    t = L.popup_texts(reason, p)
    T = C.POPUP

    @st.dialog(t["title"])
    def body() -> None:
        for para in t["body"]:
            st.markdown(para, unsafe_allow_html=True)
        if t["steps"]:
            st.markdown("<ol>" + "".join(f"<li>{s}</li>" for s in t["steps"]) + "</ol>", unsafe_allow_html=True)
        key = st.text_input(t["placeholder"], type="password", key=f"dlg_key_{pid}", label_visibility="collapsed",
                            placeholder=t["placeholder"])
        cols = st.columns(3 if pid != "gemini" else 2)
        if cols[0].button(T["btn_use_key"], type="primary", key=f"dlg_use_{pid}"):
            if key.strip():
                own_keys()[pid] = key.strip()
                st.session_state["pending_ai"] = pid
                st.session_state["goto"] = C.FIRST_PAGE
                st.session_state["toast"] = "Key saved for this visit. Press Run analysis."
                st.rerun()
            else:
                st.warning("Paste your key first.")
        i = 1
        if pid != "gemini":
            if cols[i].button(T["btn_use_gemini"], key=f"dlg_gem_{pid}"):
                st.session_state["pending_ai"] = "gemini"
                st.session_state["goto"] = C.FIRST_PAGE
                st.rerun()
            i += 1
        if cols[i].button(T["btn_use_rules"], key=f"dlg_rules_{pid}"):
            st.session_state["pending_ai"] = "rules"
            st.session_state["goto"] = C.FIRST_PAGE
            st.rerun()
        st.caption(T["key_note"])

    body()


def on_ai_change() -> None:
    pid = st.session_state.get("ai_choice", C.DEFAULT_PROVIDER)
    _, problem = L.resolve(pid, own_keys().get(pid, ""), L.site_secrets(secret_get))
    if problem:
        ask_key(problem, pid)


# ------------------------------------------------------------------ pages

def page_upload() -> None:
    st.markdown(H('<h1 class="pf-hero">', C.APP_ICON, ' <span class="pf-grad">', esc(C.APP_NAME), '</span></h1>'), unsafe_allow_html=True)
    st.markdown(H('<div class="pf-sub">', esc(C.TAGLINE), '</div>'), unsafe_allow_html=True)
    st.markdown(H('<div class="pf-steps"><div class="pf-step"><b>1</b>Add your episodes</div>',
                  '<div class="pf-step"><b>2</b>Choose how to analyse</div><div class="pf-step"><b>3</b>Press Run</div></div>'),
                unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown('<div class="pf-label">1 · Add your episodes</div>', unsafe_allow_html=True)
        files = st.file_uploader("Story files", type=["zip", "txt", "md", "pdf", "fountain"], accept_multiple_files=True,
                                 key="uploader", label_visibility="collapsed",
                                 help="A ZIP of all episodes works best. You can also add many .txt or .pdf files at once.")
        st.caption("A ZIP of all episodes, or .txt / .pdf files · up to 50 episodes at once")
        sample = st.selectbox("Sample story", [C.NO_SAMPLE] + list(C.SAMPLES), key="sample_pick", label_visibility="collapsed")

    with st.container(border=True):
        st.markdown('<div class="pf-label">2 · How should we find the promos?</div>', unsafe_allow_html=True)
        choice = st.selectbox("AI choice", L.provider_options(), key="ai_choice", on_change=on_ai_change,
                              format_func=lambda pid: L.provider_text(L.provider_by_id(pid)), label_visibility="collapsed")
        st.caption("Gemini is free and smarter but takes a few minutes for a full show (seconds for a short sample). Rule-based is instant. "
                   "OpenAI and Claude are not free: they need your own key.")

    go = st.button("✨ Run analysis", type="primary", key="run_btn")
    st.markdown(H('<div class="pf-note" style="text-align:center">', esc(C.FOOTER_NOTE), '</div>'), unsafe_allow_html=True)
    if not go:
        return

    if not files and sample == C.NO_SAMPLE:
        st.warning("Add your episodes first, or pick a sample story.")
        return
    settings, problem = L.resolve(choice, own_keys().get(choice, ""), L.site_secrets(secret_get))
    if problem:
        ask_key(problem, choice)
        st.rerun()
    try:
        with st.status("Reading your episodes and finding promos...", expanded=True) as box:
            ing = load_bytes_items([(f.name, f.getvalue()) for f in files]) if files else load_input(sample_dir(C.SAMPLES[sample]))
            box.write(f"Read {len(ing.episodes)} episode(s).")
            res = run_pipeline(ingest=ing, settings=settings, top_n=L.auto_top_n(len(ing.episodes)),
                               progress=lambda m: box.write(m))
            box.update(label="Done!", state="complete")
    except Exception as e:  # noqa: BLE001
        st.error(f"Sorry, that did not work: {e}")
        return
    st.session_state["res"] = res
    st.session_state["reviews"] = {}
    reason = L.ai_problem(res.report)
    if reason in ("quota", "badkey"):
        ask_key(reason, choice)
    st.session_state["goto"] = C.RESULT_PAGE
    st.rerun()


def tile(n: str, label: str) -> str:
    return H('<div class="pf-tile"><div class="n">', n, '</div><div class="t">', esc(label), '</div></div>')


def strength(p) -> tuple[str, str]:
    return C.STRENGTH.get(p.confidence, ("Pick", "ok"))


def page_dashboard() -> None:
    page_header("Dashboard")
    if not need_result():
        return
    res = result()
    r = res.report
    ai_on = r["mode"].startswith("llm")
    secs = r["runtime_seconds"]
    took = "under 1 s" if secs < 1 else f"{secs:.0f} s"
    # (the check that every start and end time is valid still runs inside; it is just not shown here)
    st.markdown(H('<div class="pf-tiles">', tile(str(r["input"]["episodes"]), "Episodes read"),
                  tile(str(len(res.promos)), "Promos found"),
                  tile("AI + rules" if ai_on else "Rule-based", f"How it was done · {took}"), '</div>'), unsafe_allow_html=True)
    reason = L.ai_problem(r)
    if reason == "quota":
        st.warning("The free AI limit is finished for now, so these results are Rule-based.")
        st.button("Use your own key", key="dash_ownkey", on_click=ask_key, args=("quota", st.session_state.get("ai_choice", "gemini")))
    with st.container(border=True):
        st.markdown("**Top picks**")
        rows = []
        for i, p in enumerate(res.promos[:5]):
            label, cls = strength(p)
            where = " + ".join(f"Episode {s.episode} · {fmt_ts(s.start)} → {fmt_ts(s.end)}" for s in p.segments)
            rows.append(H('<div class="pf-prow', ' first' if i == 0 else '', '"><div class="pf-rank">', str(p.rank), '</div>',
                          '<div class="pf-pm"><div class="a">', esc(where), ' · ', f"{p.duration:.0f} s", '</div><div class="b"><b>Hook:</b> ',
                          esc(p.hook), ' · <b>Cliffhanger:</b> ', esc(p.cliffhanger), '</div></div><span class="pf-pill ', cls, '">', esc(label),
                          '</span><div class="pf-sc">', str(round(p.scores.total * 100)), '</div></div>'))
        st.markdown("".join(rows), unsafe_allow_html=True)
        st.caption("Rank 1, 2, 3… is the order of the final list. It also spreads the picks across episodes and types of "
                   "moment, so the scores are close to, but not exactly, in descending order.")
    st.button("See all promos →", key="dash_all", on_click=go_to, args=("Promo Discovery",))
    notes = [friendly_warning(w) for w in r["warnings"]]
    if notes:
        with st.expander(f"Notes from this run ({len(notes)})"):
            for n in notes:
                st.markdown(f"- {n}")
    st.markdown(H('<div class="pf-note">', esc(C.FOOTER_NOTE), '</div>'), unsafe_allow_html=True)


def page_story() -> None:
    page_header("Story Intelligence")
    if not need_result():
        return
    s = result().story
    if s.get("mode") == "llm":
        st.caption("Written by the AI from the episode summaries.")
    else:
        st.caption("Counts only. Pick Gemini on the first page to get a written summary of the story.")
    for k, lbl in (("premise", "The story"), ("genre", "Genre"), ("tone", "Tone"), ("central_conflict", "Main conflict"),
                   ("audience_hook", "Why viewers keep watching")):
        if s.get(k):
            st.markdown(f"**{lbl}:** {s[k]}")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Who speaks most")
        if s.get("main_characters"):
            st.dataframe(pd.DataFrame(s["main_characters"]), hide_index=True)
        if s.get("major_reveals"):
            st.subheader("Big reveals")
            st.dataframe(pd.DataFrame(s["major_reveals"]), hide_index=True)
    with c2:
        st.subheader("What the moments are about")
        if s.get("angle_signals"):
            st.bar_chart(pd.Series(s["angle_signals"]))
        st.markdown(f"**Episodes that end with a sound sting or a cut to black:** {s.get('end_signal_rate', 0):.0%}")
        st.caption("When most episodes end that way, the end-of-episode bonus is lowered so it cannot take over the ranking.")
    for n in s.get("notes", []):
        st.caption(n)


def set_status(pid: str, status: str) -> None:
    reviews().setdefault(pid, {})["status"] = status
    save_reviews()


def clear_status(pid: str) -> None:
    """Remove the Keep / Skip / Flag decision only (time edits and notes stay)."""
    entry = reviews().get(pid)
    if entry is not None:
        entry.pop("status", None)
        if not entry:
            reviews().pop(pid, None)
    save_reviews()


def promo_card(p, emap: dict, rv: dict) -> None:
    label, cls = strength(p)
    power = round(p.scores.total * 100)
    where = " + ".join(f"Episode {s.episode} · {fmt_ts(s.start)} → {fmt_ts(s.end)}" for s in p.segments)
    bars = []
    for s in p.segments:
        ep = emap.get(s.episode)
        total = float(getattr(ep, "duration", 0) or 0)
        if total > 0:
            left = max(0.0, min(100.0, s.start / total * 100))
            width = max(1.5, min(100.0 - left, (s.end - s.start) / total * 100))
            bars.append(H('<div class="pf-bar" title="Where this clip sits inside Episode ', str(s.episode), '"><i style="left:',
                          f"{left:.1f}", '%;width:', f"{width:.1f}", '%"></i></div><div class="pf-barcap">Episode ', str(s.episode),
                          ' · where the clip sits</div>'))
    tags = "".join(f'<span class="pf-tag">{esc(t)}</span>' for t in p.tags)
    if (rv.get(p.promo_id) or {}).get("edit"):
        tags += '<span class="pf-tag">✏️ times edited in the Editing Desk (this card shows the tool\'s own pick)</span>'
    risks = "".join(f'<div class="pf-warn">⚠️ {esc(r)}</div>' for r in p.standalone_risks[:2])
    with st.container(border=True):
        st.markdown(H(
            '<div class="pf-head"><div class="pf-rank">', str(p.rank), '</div><div class="t"><b>', esc(where), '</b><br><span>',
            f"{p.duration:.0f} seconds", '</span></div><span class="pf-pill ', cls, '">', esc(label),
            '</span><div class="pf-ring" style="--p:', str(power), '" title="Ranking score, not a guarantee"><b>', str(power), '</b></div></div>',
            "".join(bars), '<div style="margin-top:8px">', tags, '</div>',
            '<div class="pf-q"><small>Hook</small>', esc(p.hook), '</div>',
            '<div class="pf-q end"><small>Cliffhanger</small>', esc(p.cliffhanger), '</div>',
            '<div class="pf-why"><b>Why it works:</b> ', esc(p.why), '</div>',
            ('<div class="pf-why"><b>Editing tip:</b> ' + esc(p.cut_note) + '</div>') if p.cut_note else "", risks), unsafe_allow_html=True)
        with st.expander("Read the scene"):
            lines = []
            for t in p.transcript[:40]:
                if t["kind"] == "dialogue":
                    lines.append(H('<div class="pf-line"><code>', fmt_ts(t["start"]), '</code><b>', esc(t.get("speaker")), '</b> ', esc(t["text"]), '</div>'))
                else:
                    lines.append(H('<div class="pf-line cam"><code>', fmt_ts(t["start"]), '</code><i>[', esc(t["kind"]), '] ', esc(t["text"]), '</i></div>'))
            st.markdown("".join(lines), unsafe_allow_html=True)
        with st.expander("See the scores"):
            cols = st.columns(4)
            for i, d in enumerate(WEIGHTS):
                cols[i % 4].metric(SCORE_LABELS.get(d, d), f"{getattr(p.scores, d):.2f}")
            st.caption(p.rank_reason)
            for n in p.notes:
                st.caption("note: " + n)


def page_discovery() -> None:
    page_header("Promo Discovery")
    if not need_result():
        return
    res = result()
    emap = {e.number: e for e in res.episodes}
    rv = reviews()
    with st.expander("Filters"):
        show = st.radio("Show", ["All", "Strong picks", "Good picks", "Double-check"], horizontal=True, key="f_show")
        tags = sorted({t for p in res.promos for t in p.tags})
        angle = st.multiselect("Type of moment", tags, key="f_angle")
        eps = sorted({s.episode for p in res.promos for s in p.segments})
        ep_f = st.multiselect("Episode", eps, key="f_ep")
    want = {"All": None, "Strong picks": "high", "Good picks": "medium", "Double-check": "low"}[show]
    shown = 0
    for p in res.promos:
        if want and p.confidence != want:
            continue
        if angle and not set(angle) & set(p.tags):
            continue
        if ep_f and not {s.episode for s in p.segments} & set(ep_f):
            continue
        shown += 1
        promo_card(p, emap, rv)
    if shown == 0:
        st.info("No promos match the filters.")
    st.markdown(H('<div class="pf-note">', esc(C.FOOTER_NOTE), '</div>'), unsafe_allow_html=True)


# ------------------------------------------------------------------ the Editing Desk (read the script, move the cut, keep or skip)

def _emap() -> dict:
    return {e.number: e for e in result().episodes}


def _desk_promo(pid: str):
    return next(p for p in result().promos if p.promo_id == pid)


def desk_current(p, pid: str) -> tuple[float, float]:
    """The times now in force for a single-episode promo: the editor's saved edit, or the tool's own pick."""
    e = (reviews().get(pid) or {}).get("edit")
    s0 = p.segments[0]
    return (float(e["start"]), float(e["end"])) if e else (s0.start, s0.end)


def desk_say(pid: str, ok: bool, text: str) -> None:
    st.session_state["desk_msg"] = {"pid": pid, "ok": ok, "text": text}


def desk_commit(pid: str, start: float, end: float, note: str = "") -> bool:
    """Check a new start and end. If it is fine, save it as the editor's edit. Either way the two boxes end up showing
    the saved times, so a refused move simply changes nothing."""
    p = _desk_promo(pid)
    emap = _emap()
    s0 = p.segments[0]
    ok, msg = check_edit(emap[s0.episode], emap, start, end)
    if ok:
        entry = reviews().setdefault(pid, {})
        if abs(start - s0.start) < 0.005 and abs(end - s0.end) < 0.005:
            entry.pop("edit", None)
            if not entry:
                reviews().pop(pid, None)
            msg += " · back to the tool's own pick"
        else:
            entry["edit"] = {"episode": s0.episode, "start": round(start, 2), "end": round(end, 2)}
            msg += " · saved" + note
        save_reviews()
    cs, ce = desk_current(p, pid)
    st.session_state[f"ds_{pid}"] = cs
    st.session_state[f"de_{pid}"] = ce
    desk_say(pid, ok, msg)
    return ok


def desk_nudge(pid: str, which: str, delta: float) -> None:
    p = _desk_promo(pid)
    ep = _emap()[p.segments[0].episode]
    cs, ce = desk_current(p, pid)
    new, slid = nudge_time(ep, which, cs if which == "start" else ce, delta)
    ns, ne = (new, ce) if which == "start" else (cs, new)
    desk_commit(pid, ns, ne, " · moved on to the edge of the spoken line, so no line is cut in half" if slid else "")


def desk_typed(pid: str) -> None:
    desk_commit(pid, float(st.session_state[f"ds_{pid}"]), float(st.session_state[f"de_{pid}"]))


def desk_reset(pid: str) -> None:
    s0 = _desk_promo(pid).segments[0]
    desk_commit(pid, s0.start, s0.end)


def desk_step(delta: int) -> None:
    ids = [p.promo_id for p in result().promos]
    cur = st.session_state.get("desk_pick", ids[0])
    i = ids.index(cur) if cur in ids else 0
    st.session_state["desk_pick"] = ids[max(0, min(len(ids) - 1, i + delta))]


def page_desk() -> None:
    page_header("Editing Desk")
    if not need_result():
        return
    res = result()
    if not res.episodes:
        st.info("The script is not available for this result.")
        return
    rv = reviews()
    emap = _emap()
    done = sum(1 for v in rv.values() if v.get("status") in ("approved", "rejected"))
    st.progress(done / max(1, len(res.promos)), text=f"{done} of {len(res.promos)} promos decided (Keep or Skip)")
    ids = [p.promo_id for p in res.promos]
    if st.session_state.get("desk_pick") not in ids:
        st.session_state["desk_pick"] = ids[0]
    pid = st.selectbox("Promo", ids, key="desk_pick",
                       format_func=lambda x: next(f"#{p.rank}  {x}  [{STATUS_TEXT.get(decision_of(rv, x), '-')}]"
                                                  for p in res.promos if p.promo_id == x))
    p = _desk_promo(pid)
    n1, n2, _ = st.columns([1, 1, 3])
    n1.button("◀ Previous promo", key="desk_prev", on_click=desk_step, args=(-1,))
    n2.button("Next promo ▶", key="desk_next", on_click=desk_step, args=(1,))

    single = len(p.segments) == 1
    shown = p
    if single:
        cs, ce = desk_current(p, pid)
        shown = apply_edit(p, emap, cs, ce)
    where = "  +  ".join(f"Episode {s.episode} · {fmt_ts(s.start)} → {fmt_ts(s.end)}" for s in shown.segments)
    st.markdown(f"**#{p.rank}  {where}**  ({shown.duration:.1f} s)")
    st.markdown(H('<div class="pf-q"><small>Hook</small>', esc(shown.hook), '</div>',
                  '<div class="pf-q end"><small>Cliffhanger</small>', esc(shown.cliffhanger), '</div>'), unsafe_allow_html=True)

    # ---- the script: the whole episode, the promo in yellow, opened at the start of the clip
    seg = shown.segments[0]
    if len(shown.segments) > 1:
        ep_no = st.radio("Episode to show", [s.episode for s in shown.segments], horizontal=True, key="desk_ep")
        seg = next(s for s in shown.segments if s.episode == ep_no)
    st.caption(f"Episode {seg.episode} · the whole script. The yellow part is the promo. "
               "The box opens at the clip, scroll for the rest.")
    components.html(script_view_html(emap[seg.episode], seg.start, seg.end), height=430)

    # ---- move the cut (one episode only)
    if single:
        ep = emap[seg.episode]
        st.session_state[f"ds_{pid}"] = cs                  # the boxes always show the saved times
        st.session_state[f"de_{pid}"] = ce
        with st.container(key="desk_times"):
            c1, c2 = st.columns(2)
            for col, which, label, key, val in ((c1, "start", "Start (seconds)", f"ds_{pid}", cs),
                                                 (c2, "end", "End (seconds)", f"de_{pid}", ce)):
                with col:
                    st.markdown(f'<div class="pf-label">{label}</div>', unsafe_allow_html=True)
                    b1, b2, b3 = st.columns([1, 1.7, 1])
                    b1.button(f"− {STEP:g}", key=f"{which}_m_{pid}", on_click=desk_nudge, args=(pid, which, -STEP))
                    b2.number_input(label, min_value=0.0, max_value=float(ep.duration), step=STEP, format="%.2f", key=key,
                                    label_visibility="collapsed", on_change=desk_typed, args=(pid,))
                    b3.button(f"+ {STEP:g}", key=f"{which}_p_{pid}", on_click=desk_nudge, args=(pid, which, STEP))
        msg = st.session_state.get("desk_msg")
        if msg and msg["pid"] == pid:
            (st.success if msg["ok"] else st.error)(msg["text"])
        else:
            ok, text = check_edit(ep, emap, cs, ce)
            (st.success if ok else st.error)(text)
        if (rv.get(pid) or {}).get("edit"):
            st.button("↺ Go back to the tool's own times", key="desk_reset", on_click=desk_reset, args=(pid,))
    else:
        st.caption("This promo joins more than one episode, so its times cannot be moved here. "
                   "You can still Keep, Skip or Flag it.")

    # ---- the decision
    st.markdown('<div class="pf-label" style="margin-top:.8rem">Your decision</div>', unsafe_allow_html=True)
    b1, b2, b3, b4 = st.columns(4)
    b1.button("Keep", key="rv_ok", on_click=set_status, args=(pid, "approved"))
    b2.button("Skip", key="rv_no", on_click=set_status, args=(pid, "rejected"))
    b3.button("Flag", key="rv_flag", on_click=set_status, args=(pid, "flagged"))
    b4.button("Clear", key="rv_clear", on_click=clear_status, args=(pid,))
    cur = decision_of(rv, pid)
    st.caption("Your decision for this promo: " + STATUS_TEXT.get(cur, "not decided yet"))
    entry = rv.get(pid) or {}
    note = st.text_input("Notes", value=entry.get("notes", ""), key=f"notes_{pid}")
    if note != entry.get("notes", ""):
        if note:
            rv.setdefault(pid, {})["notes"] = note
        elif pid in rv:
            rv[pid].pop("notes", None)
        save_reviews()
    st.caption("Your choices are kept only while this page is open. When you are done, go to Export to save your work.")
    st.button("Go to Export →", key="desk_export", type="primary", on_click=go_to, args=("Export",))
    st.markdown(H('<div class="pf-note">', esc(C.FOOTER_NOTE), '</div>'), unsafe_allow_html=True)


# ------------------------------------------------------------------ export

def promos_csv_bytes(promos, rv: dict | None = None, originals: dict | None = None) -> bytes:
    rv = rv or {}
    extra = bool(rv)
    cols = CSV_COLUMNS + (["decision", "editor_notes", "times_edited_from"] if extra else [])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for p in promos:
        row = promo_to_row(p)
        if extra:
            r = rv.get(p.promo_id) or {}
            row["decision"] = {"approved": "kept", "rejected": "skipped", "flagged": "flagged"}.get(r.get("status", ""), "")
            row["editor_notes"] = r.get("notes", "")
            o = (originals or {}).get(p.promo_id)
            row["times_edited_from"] = (f"{fmt_ts(o.segments[0].start)}-{fmt_ts(o.segments[0].end)}"
                                        if o is not None and r.get("edit") else "")
        w.writerow(row)
    return buf.getvalue().encode("utf-8-sig")


def review_sheet_bytes(promos, rv: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "promo_id", "segments", "hook", "cliffhanger", "your decision (approved/rejected/flagged)", "notes"])
    for p in promos:
        r = promo_to_row(p)
        w.writerow([p.rank, p.promo_id, r["segments"], p.hook, p.cliffhanger, (rv.get(p.promo_id) or {}).get("status", ""),
                    (rv.get(p.promo_id) or {}).get("notes", "")])
    return buf.getvalue().encode("utf-8-sig")


def page_export() -> None:
    page_header("Export")
    if not need_result():
        return
    res = result()
    rv = reviews()
    emap = _emap()
    n_all = len(res.promos)
    n_kept = sum(1 for p in res.promos if decision_of(rv, p.promo_id) == "approved")
    n_edit = sum(1 for p in res.promos if len(p.segments) == 1 and (rv.get(p.promo_id) or {}).get("edit"))
    options = ["all"] + (["kept"] if n_kept else [])
    if st.session_state.get("exp_scope") not in options:
        st.session_state["exp_scope"] = "all"
    with st.container(border=True):
        st.markdown('<div class="pf-label">What should we export?</div>', unsafe_allow_html=True)
        scope = st.radio("What should we export?", options, key="exp_scope", label_visibility="collapsed",
                         format_func=lambda o: f"All promos ({n_all})" if o == "all" else f"Only the promos I kept ({n_kept})")
        if not n_kept:
            st.caption("Want only some of them? Mark promos with Keep in the Editing Desk and a second choice appears here.")
        if n_edit:
            st.caption(f"{n_edit} promo{'s have' if n_edit != 1 else ' has'} times you changed in the Editing Desk. "
                       "The new times are used.")
    originals = {p.promo_id: p for p in res.promos}
    promos = effective_promos(res.promos, emap, rv, kept_only=(scope == "kept"))
    files = promo_text_files(promos, emap)
    c1, c2 = st.columns(2)
    c1.download_button("⬇ Promos (spreadsheet, CSV)", promos_csv_bytes(promos, rv, originals), "promos.csv", "text/csv", key="dl_csv")
    c2.download_button("⬇ My Keep / Skip choices (CSV)", review_sheet_bytes(promos, rv), "my_choices.csv", "text/csv", key="dl_review")
    st.markdown('<div class="pf-label" style="margin-top:.8rem">Text files, one for each promo</div>', unsafe_allow_html=True)
    st.caption("Each file is written in the same style as the episode files you uploaded, with only the lines of the promo.")
    if len(files) > 3:
        st.download_button(f"⬇ All {len(files)} promo text files (ZIP)", zip_bytes(files), "promo_texts.zip", "application/zip",
                           key="dl_txt_zip")
    else:
        for i, (name, text) in enumerate(files):
            st.download_button(f"⬇ {name}", text.encode("utf-8"), name, "text/plain", key=f"dl_txt_{i}")
    with st.expander("For developers"):
        st.download_button("promos.json", json.dumps({"mode": res.report["mode"], "warnings": res.report["warnings"],
                                                      "promos": [promo_to_dict(p) for p in promos]}, indent=2,
                                                     ensure_ascii=False).encode("utf-8"), "promos.json", "application/json", key="dl_json")
        st.download_button("run_report.json", json.dumps(res.report, indent=2, ensure_ascii=False).encode("utf-8"),
                           "run_report.json", "application/json", key="dl_report")
        st.download_button("reviews.json (Keep / Skip choices and time edits, for the evaluate command)",
                           json.dumps(reviews(), indent=2).encode("utf-8"), "reviews.json", "application/json", key="dl_reviews")
    st.caption("Your files are only used for this analysis. If your story is confidential, download what you need and close the tab.")


# ------------------------------------------------------------------ router

PAGE_FUNCS = {"Upload & Analyze": page_upload, "Dashboard": page_dashboard, "Story Intelligence": page_story,
              "Promo Discovery": page_discovery, "Editing Desk": page_desk, "Export": page_export}

inject_css()

# things set by the pop-up or after a run, applied BEFORE the widgets are created
if "goto" in st.session_state:
    st.session_state["page_choice"] = st.session_state.pop("goto")
if "pending_ai" in st.session_state:
    st.session_state["ai_choice"] = st.session_state.pop("pending_ai")
st.session_state.setdefault("page_choice", C.FIRST_PAGE)
st.session_state.setdefault("ai_choice", C.DEFAULT_PROVIDER)
st.session_state.setdefault("sample_pick", C.NO_SAMPLE)
st.session_state["ai_choice"] = st.session_state["ai_choice"]          # keep these when the visitor changes page
st.session_state["sample_pick"] = st.session_state["sample_pick"]

with st.sidebar:
    st.markdown(H('<div style="font-size:1.4rem;font-weight:800;margin-bottom:.8rem" class="pf-grad">', C.APP_ICON, ' ',
                  esc(C.APP_NAME), '</div>'), unsafe_allow_html=True)
    page = st.radio("Go to", PAGE_NAMES, key="page_choice", label_visibility="collapsed",
                    format_func=lambda n: f"{PAGE_META[n][0]}  {n}")
    res_ = result()
    if res_ is not None:
        st.caption(f"Loaded: {len(res_.promos)} promos from {res_.report['input']['episodes']} episodes")

if "toast" in st.session_state:
    st.toast(st.session_state.pop("toast"))
if "ask_key" in st.session_state:
    _reason, _pid = st.session_state.pop("ask_key")
    open_key_dialog(_reason, _pid)

PAGE_FUNCS[page]()
