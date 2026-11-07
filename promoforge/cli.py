"""Command line: run / evaluate (doctor lives in doctor.py so it works without third-party packages)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _progress(msg: str) -> None:
    print("  " + msg, flush=True)


def cmd_run(a) -> int:
    from .llm_provider import load_settings
    from .pipeline import run_pipeline
    overrides = {"provider": a.provider, "model": a.model, "max_calls": a.max_calls, "rpm": a.rpm}
    s = load_settings(a.env, overrides)
    if a.rules_only:
        s.provider = "none"
    print(f"PromoForge AI: reading {a.input}")
    print(f"  provider: {s.provider if s.provider != 'none' else 'none (rules-only)'}")
    res = run_pipeline(input_path=a.input, out_dir=a.out, settings=s, top_n=a.top_n, progress=_progress)
    r = res.report
    print()
    print(f"Mode: {r['mode']}")
    print(f"Episodes: {r['input']['episodes']}   Promos written: {len(res.promos)}   Runtime: {r['runtime_seconds']} s")
    ok = sum(p.validation.ok for p in res.promos)
    print(f"Promos passing Python validation: {ok}/{len(res.promos)}")
    if r.get("llm"):
        l = r["llm"]
        print(f"AI calls: {l.get('calls_made', 0)} (cache hits {l.get('cache_hits', 0)}), model used: {l.get('model_used', '?')}")
    for w in r["warnings"][:8]:
        print("  WARNING: " + w[:220])
    print(f"Outputs saved in: {Path(a.out).resolve()}")
    print("  promos.json, promos.csv, run_report.json, story_intelligence.json, review_sheet.csv, failure_analysis_*.md")
    return 0


def cmd_evaluate(a) -> int:
    from .evaluation import compute_metrics, load_json
    from .pipeline import load_run
    res = load_run(a.run)
    if not res.episodes:
        print("This run folder has no parsed_script.json; metrics that need the script cannot be computed.")
        return 1
    reviews = load_json(a.reviews) if a.reviews else load_json(Path(a.run) / "reviews.json")
    gold = load_json(a.gold) if a.gold else None
    m = compute_metrics(res.promos, res.episodes, reviews, gold)
    print(json.dumps(m, indent=2))
    if a.save:
        Path(a.run, "evaluation.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
        print(f"Saved {Path(a.run, 'evaluation.json')}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m promoforge", description="Find the best promo clips in a microdrama.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="analyse a ZIP / folder / file of screenplays")
    r.add_argument("--input", required=True, help="ZIP, folder, or a single .txt/.md/.pdf")
    r.add_argument("--out", required=True, help="output folder")
    r.add_argument("--provider", help="gemini | openai | anthropic | mock | none (default: from .env, else none)")
    r.add_argument("--model", help="leave empty for automatic model choice")
    r.add_argument("--top-n", type=int, default=40)
    r.add_argument("--max-calls", type=int, help="AI call budget")
    r.add_argument("--rpm", type=int, help="AI requests per minute")
    r.add_argument("--env", help="path to a .env file")
    r.add_argument("--rules-only", action="store_true", help="never call an AI model")
    r.set_defaults(fn=cmd_run)
    e = sub.add_parser("evaluate", help="honest metrics for a finished run")
    e.add_argument("--run", required=True, help="output folder of a run")
    e.add_argument("--reviews", help="reviews.json (human labels)")
    e.add_argument("--gold", help="gold.json: list of {episode,start,end}")
    e.add_argument("--save", action="store_true")
    e.set_defaults(fn=cmd_evaluate)
    sub.add_parser("doctor", help="plain-words setup check")
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
