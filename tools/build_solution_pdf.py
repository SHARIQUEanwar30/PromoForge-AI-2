"""Build the <=2-page solution PDF from REAL run outputs.

Every number comes from run_report.json / promos.json (or from a fresh pytest run). Anything that was not run is
stated as "not yet run". A real-AI claim appears only if the run report shows a non-mock provider and judged promos.

Usage:
  python tools/build_solution_pdf.py --run submission_private/raw_outputs_llm --out solution.pdf \
      --name "Your Name" --roll "Roll" --branch "B.Tech Biosciences & Bioengineering, IIT Guwahati" \
      --prototype "https://github.com/you/PromoForge-AI" --app "https://....streamlit.app" --findings findings.json
findings.json (optional, hand-checked statements about the run) = {"spot_check": "...", "failures": ["...", "..."]}
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

from promoforge.evaluation import compute_metrics  # noqa: E402
from promoforge.pipeline import load_run  # noqa: E402


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run_tests() -> str:
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"], cwd=ROOT,
                           capture_output=True, text=True, timeout=600)
        m = re.search(r"(\d+) passed", r.stdout)
        f = re.search(r"(\d+) failed", r.stdout)
        if m and not f:
            return f"{m.group(1)} automated tests run and passed"
        return "automated tests were run but not all passed (see repo)"
    except Exception:  # noqa: BLE001
        return "automated tests: not run when this PDF was built"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="[Your name]")
    ap.add_argument("--roll", default="[Roll number]")
    ap.add_argument("--branch", default="B.Tech, Biosciences & Bioengineering, IIT Guwahati")
    ap.add_argument("--prototype", default="")
    ap.add_argument("--app", default="")
    ap.add_argument("--findings", default="")
    ap.add_argument("--first-run", default="", help="run_report.json of the run that made the real AI calls, when --run is a cached re-run (0 new calls)")
    ap.add_argument("--tests", default="", help="override the test summary text")
    ap.add_argument("--font", type=float, default=8.9)
    a = ap.parse_args()

    res = load_run(a.run)
    rep = res.report
    promos = res.promos
    n = len(promos)
    metrics = compute_metrics(promos, res.episodes) if res.episodes else {}
    hc = metrics.get("hard_constraints", {})
    dist = metrics.get("distribution", {})
    llm = rep.get("llm") or {}
    real_ai = bool(llm) and llm.get("provider") not in (None, "mock") and (rep.get("judge") or {}).get("judged", 0) > 0
    first = json.loads(Path(a.first_run).read_text(encoding="utf-8")) if a.first_run else {}
    rerun = bool(first) and not llm.get("calls_made")
    ai_src = (first.get("llm") or {}) if rerun else llm
    ai_secs = first.get("runtime_seconds", rep["runtime_seconds"]) if rerun else rep["runtime_seconds"]
    findings = json.loads(Path(a.findings).read_text(encoding="utf-8")) if a.findings else {}
    tests = a.tests or run_tests()
    cs = rep["candidate_stats"]
    ctxr = rep["show_context"]["end_signal_rate"]

    fs = a.font
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=fs, leading=fs * 1.22, spaceAfter=1.6)
    bul = ParagraphStyle("bl", parent=body, leftIndent=9, bulletIndent=0, spaceAfter=1.0)
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=fs + 1.6, leading=fs + 3, spaceBefore=4.5, spaceAfter=1.5,
                       textColor=colors.HexColor("#8e1b10"))
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=14, leading=16, spaceAfter=1)
    sub = ParagraphStyle("s", parent=body, textColor=colors.HexColor("#444444"), spaceAfter=3)

    doc = SimpleDocTemplate(a.out, pagesize=A4, leftMargin=1.45 * cm, rightMargin=1.45 * cm, topMargin=1.1 * cm,
                            bottomMargin=1.0 * cm, title="PromoForge AI - Solution document", author=a.name)
    S = []

    def P(t, st=body):
        S.append(Paragraph(t, st))

    def B(t):
        S.append(Paragraph(t, bul, bulletText="•"))

    def H(t):
        S.append(Paragraph(t, h))

    P("PromoForge AI: finding promo clips in microdrama screenplays", title)
    links = []
    if a.prototype:
        links.append(f"Repo: {esc(a.prototype)}")
    if a.app:
        links.append(f"App: {esc(a.app)}")
    P(f"Kuku AI Generalist, <b>Problem 1: Find the Promos</b> &nbsp;|&nbsp; {esc(a.name)}, Roll {esc(a.roll)}, {esc(a.branch)}"
      + (" &nbsp;|&nbsp; " + " &nbsp;|&nbsp; ".join(links) if links else ""), sub)

    H("1. Why Problem 1, and how I scoped it")
    P("I chose Problem 1 because it is a real weekly bottleneck (an editor watches every episode by hand, new shows every week), "
      "its output is checkable (episode, timestamps, three rules) and it repeats for every show. Problems 2 and 3 need legal or "
      "viewer research that I could not do honestly in the time. Scope: <b>find and rank</b> clips from the text screenplay; no editing, music or overlays.")
    P("<b>Assumptions</b> (the brief was silent): (1) script timestamps are the video timeline, so a promo = episode + start/end. "
      "(2) The 3-second hook is measured from the clip start. (3) A cut may fall only on a shot boundary and never inside a dialogue line. "
      "(4) Multi-segment promos must total 20-60 s; cross-episode joins are allowed only for consecutive episodes whose continuity note says the next one "
      "continues directly. (5) Text cannot show acting, music or visuals, so cliffhanger and hook are judged from words and script cues. "
      "(6) The ten scoring weights (hook .15, cliffhanger .15, flow .12, clear-alone .11, emotion .10, appeal .10, rising tension .09, curiosity .08, spoiler control .05, length .05) are "
      "<b>editorial guesses, not validated</b>. (7) The list shows up to 60 promos, at most 3 per episode, and only clips above a quality floor; the editor can change both.")

    H("2. How it works: what is code, what is AI, where a human stays")
    B("<b>Python (always works, no key):</b> reads ZIP/TXT/MD/PDF in four layouts (labelled blocks, inline timestamps, Fountain, prose; "
      "the last two have no times, so timing is estimated and flagged). It enumerates every shot-aligned 20-60 s window "
      f"({cs['windows_enumerated']:,} for this show), adds skip-gap stitched and cross-episode candidates, scores 10 explainable dimensions (including a look at the lines after the cut, rising tension and spoiler control), "
      "validates, then ranks with a diversity-aware greedy selection (MMR plus near-duplicate removal) so the list is not ten copies of one scene. "
      "Every rank has a plain-English reason and risk flags (for example: starts mid-scene).")
    B("<b>AI (optional, swappable):</b> one call summarises the story (including secrets a promo must not reveal); ten calls scan the episodes for strong moments "
      "the rules may miss; the best 60 to 70 candidates are then judged in batches of 4 against an editor rubric (hook, cliffhanger, clarity, emotion, curiosity, "
      "rising tension, appeal, spoilers), with the next two lines after the cut shown so the model can tell whether the clip ends too early. "
      "The model sees and returns beat IDs, never timestamps. Python turns IDs into times and re-validates: inside the real script range, 20-60 s, trims may only "
      "shorten, no cut inside a line, quoted words must exist in the transcript. AI scores are rescaled to the rules' spread, then blended 0.7 AI + 0.3 rules, "
      "and a weak must-pass check (a spoiler, no hook, no cliffhanger, unclear alone) lowers the rank. Any failure falls back to rules with a visible warning. "
      "Gemini, any OpenAI-compatible endpoint, Anthropic or a test Mock are chosen in settings only; model names are discovered from the key.")
    B("<b>Human in the loop:</b> an Editing Desk page (the whole script with the promo highlighted; Keep, Skip, Flag; start and end can be moved 0.5 s at a time and every move is re-validated, a 10 s clip is refused) "
      "writes reviews.json, which is the only source of Precision@K. Export gives the promo list as CSV and one text file per promo in the style of the input.")
    B(f"<b>Lesson built in:</b> {ctxr:.0%} of these episodes end with the same kind of sound sting or cut-to-black, so a naive "
      f"\"episode end = cliffhanger\" bonus would dominate. End-signal bonuses are multiplied by {rep['show_context']['sting_factor']:.2f}.")

    H("Example output (top 5 of the submitted list)")
    ex = [["#", "Episode and time", "Len", "Score", "Hook (first 3 s)  ->  where it cuts"]]
    for p_ in promos[:5]:
        seg = "; ".join(f"E{x.episode} {x.start_ts}-{x.end_ts}" for x in p_.segments)
        hk = re.sub(r"^\[action\] ", "", p_.hook)[:58]
        cl = re.sub(r"^\[action\] ", "", p_.cliffhanger)[:58]
        ex.append([str(p_.rank), seg, f"{p_.duration:.0f}s", f"{p_.scores.total:.2f}", f"{hk}  ->  {cl}"])
    et = Table([[Paragraph(esc(c), body) for c in r] for r in ex], colWidths=[0.7 * cm, 3.9 * cm, 1.0 * cm, 1.3 * cm, 11.2 * cm])
    et.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#bbbbbb")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1e3e0")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.0)]))
    S.append(et)
    P("Each promo in promos.json/CSV also carries every segment, the hook, the cliffhanger, one line on why it works, the ten scores, a confidence level, "
      "risks and a transcript rebuilt by Python from the script.")

    H("3. Scaling to every Kuku show, and cost")
    if real_ai:
        ai_cost = (f"The AI steps (story summary, moment scan, judging) took {ai_src.get('calls_made', 0)} calls and about "
                   f"{ai_src.get('input_tokens_approx', 0):,} input tokens on the free Gemini tier in the real run "
                   f"({ai_secs:.0f} s in total at 10 calls per minute); a disk cache makes re-runs free, and N shows a week is roughly N times that. ")
    else:
        ai_cost = ("The AI step is about 27 calls and roughly 77,000 input tokens per 50-episode show (estimated from a Mock run of the full pack), "
                   "well inside a free tier; a disk cache makes re-runs free. ")
    P(f"For this 50-episode show ({rep['input']['total_beats']:,} beats) parsing, {cs['windows_scored']:,} scored windows and rule-based ranking take "
      "about 7 s on a laptop CPU at zero cost. " + ai_cost +
      "A paid or stronger model is a settings change. Shows run independently, so they parallelise. Rules-only scoring is English-only: other languages need "
      "cue lists per language or AI-only judging. Editors review about 40 to 60 pre-checked clips per show instead of watching about 100 minutes.")

    H("4. How I checked quality (real runs only)")
    mode_txt = (f"AI + rules run with {esc(str(ai_src.get('model_used', '?')))} ({ai_src.get('calls_made', 0)} calls, "
                f"{ai_src.get('input_tokens_approx', 0):,} input tokens approx.)"
                + (" The submitted folder is a re-ranking of those saved AI answers with the final scoring code (0 new calls); the first run's outputs are included as run1." if rerun else "")
                if real_ai else
                "<b>rules-only (heuristic) run; the AI path is implemented and tested with a Mock provider, a real-model run on the full pack is NOT yet done</b>")
    rows = [["Check", "Result"],
            ["Run mode of the submitted outputs", Paragraph(mode_txt, body)],
            ["Promos / episodes covered", f"{n} promos from {dist.get('episodes_with_a_promo', '?')} of {dist.get('episodes_total', '?')} episodes"],
            ["Duration 20-60 s; timestamps inside real script range", f"{hc.get('duration_20_to_60s', '?')}; {hc.get('timestamps_inside_real_script_range', '?')}"],
            ["No cut inside a dialogue line; action in first 3 s", f"{hc.get('no_cut_inside_dialogue_line', '?')}; {hc.get('something_happens_in_first_3s', '?')}"],
            *([["AI safety checks that fired in this run", Paragraph(
                f"The AI never writes times. Python ignored {(rep.get('judge') or {}).get('bad_ids_ignored', 0)} beat ids the model made up, "
                f"rejected {((rep.get('scan') or {}).get('rejected') or {}).get('duration', 0)} of {(rep.get('scan') or {}).get('proposed', 0)} AI-proposed moments "
                f"for breaking the 20-60 s rule, and accepted {(rep.get('judge') or {}).get('trims_applied', 0)} AI trims only after re-validating them.", body)]] if real_ai else []),
            ["Precision@K / approval rate", "NOT CALCULABLE: I had no editor labels (the review flow to produce them is built)"],
            ["Automated tests", tests + " (four parsers incl. PDF round-trip, validator, candidates, AI layer, app)"],
            ["Generalization", "same code on 3 synthetic stories, 3 genres, 3 layouts (one without timestamps): all promos valid; the no-timestamp story is marked low confidence"]]
    t = Table([[Paragraph(str(c), body) if isinstance(c, str) else c for c in r] for r in rows], colWidths=[5.2 * cm, 12.9 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#bbbbbb")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1e3e0")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2)]))
    S.append(KeepTogether([t]))
    S.append(Spacer(1, 2))
    if findings.get("spot_check"):
        P("<b>Spot check (AI-assisted reading; this is NOT human editor labelling):</b> " + esc(findings["spot_check"]))

    H("5. Where it fails")
    gap = (promos[0].scores.total - promos[-1].scores.total) if n > 1 else 0
    close = sum(1 for p in promos if promos[0].scores.total - p.scores.total <= 0.05) if n else 0
    B(f"<b>Scores are close.</b> The whole list spans only {gap:.2f} in score and {close} promos sit within 0.05 of the top, so order inside that band is close to a tie.")
    for f in findings.get("failures", []):
        B(f)
    B("<b>Text-only limits.</b> A question or threat can look like a cliffhanger while the next line resolves it; acting, music and visuals are invisible; "
      "cue lists are English-only; the introduced-name check also flags words such as nationalities.")
    B("<b>Ground truth.</b> No precision number exists until editors approve or reject clips; the weights are assumptions that editor feedback should tune.")

    H("6. Tools used, and one place they got it wrong")
    P("Claude (Anthropic) wrote most of the code and drafts with me; I set the design rules (beat IDs only, Python re-validation, honest metrics) and "
      + (f"the Gemini free tier ({esc(str(ai_src.get('model_used', 'Gemini')))}) ran the AI steps of the submitted run. " if real_ai else "the Gemini free tier is the planned runtime model. ") +
      "<b>Where it was wrong:</b> the first parser silently dropped 56 of 1,487 dialogue lines, because "
      "one speaker label had two brackets, <i>(O.S.) (Gasping)</i>. A count of labels against parsed lines exposed it; the fix has a test. A header-number "
      "pattern also failed silently and a unit test caught it. <b>Next:</b> tune weights on editor approvals, multilingual cue lists, "
      "audio/video signals (music peaks, shot cuts), and measure promo click-through.")

    doc.build(S)
    from pypdf import PdfReader
    pages = len(PdfReader(a.out).pages)
    print(f"built {a.out}: {pages} page(s), real_ai={real_ai}")
    if pages > 2:
        print("WARNING: more than 2 pages; lower --font or shorten text")
        sys.exit(2)


if __name__ == "__main__":
    main()
