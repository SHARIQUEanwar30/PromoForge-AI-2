import ast
import json
import subprocess
import sys
from pathlib import Path

from promoforge.evaluation import (NC, compute_metrics, failure_analysis, gold_recall, hard_constraints,
                                   precision_at_k)
from promoforge.llm_provider import Settings
from promoforge.pipeline import load_run, run_pipeline

ROOT = Path(__file__).resolve().parent.parent


def test_rules_only_pipeline_end_to_end(sample_dirs, tmp_path):
    res = run_pipeline(input_path=sample_dirs["story_labelled"], out_dir=tmp_path, settings=Settings(provider="none"), top_n=8)
    assert res.report["mode"].startswith("rules-only")
    assert any("RULES-ONLY" in w for w in res.report["warnings"])
    for name in ["promos.json", "promos.csv", "run_report.json", "story_intelligence.json", "review_sheet.csv",
                 "failure_analysis_private.md", "failure_analysis_public_redacted.md", "parsed_script.json"]:
        assert (tmp_path / name).exists(), name
    data = json.loads((tmp_path / "promos.json").read_text(encoding="utf-8"))
    p = data["promos"][0]
    for k in ["rank", "segments", "hook", "cliffhanger", "why_it_works", "scores", "confidence", "timestamps_valid", "transcript"]:
        assert k in p
    assert p["segments"][0]["start_ts"] and p["segments"][0]["episode"]
    assert all(x["timestamps_valid"] for x in data["promos"])


def test_mock_llm_pipeline_marks_blended_mode(sample_dirs, tmp_path):
    s = Settings(provider="mock", cache_dir=str(tmp_path / "c"), rpm=6000)
    res = run_pipeline(input_path=sample_dirs["story_labelled"], out_dir=tmp_path / "o", settings=s, top_n=6)
    assert res.report["mode"] == "llm+heuristic" and res.report["llm"]["provider"] == "mock"
    assert all(p.scoring_mode == "llm+heuristic" for p in res.promos)
    assert not any("RULES-ONLY" in w for w in res.report["warnings"])


def test_pipeline_falls_back_to_rules_when_ai_unavailable(sample_dirs, tmp_path):
    s = Settings(provider="gemini", api_key="", cache_dir=str(tmp_path / "c"))    # no key -> config error
    res = run_pipeline(input_path=sample_dirs["story_labelled"], settings=s, top_n=5)
    assert res.report["mode"].startswith("rules-only")
    assert any("heuristic" in w.lower() for w in res.report["warnings"])
    assert res.promos and all(p.validation.ok for p in res.promos)


def test_all_formats_through_pipeline(sample_dirs, tmp_path):
    for name, d in sample_dirs.items():
        res = run_pipeline(input_path=d, settings=Settings(provider="none"), top_n=5)
        assert res.promos and all(p.validation.ok for p in res.promos), name
        assert res.report["input"]["timing_estimated"] == (name == "story_fountain")


def test_load_run_roundtrip(sample_dirs, tmp_path):
    res = run_pipeline(input_path=sample_dirs["story_labelled"], out_dir=tmp_path, settings=Settings(provider="none"), top_n=6)
    back = load_run(tmp_path)
    assert [p.promo_id for p in back.promos] == [p.promo_id for p in res.promos]
    assert len(back.episodes) == len(res.episodes)


# ---------------------------------------------------------------- honest evaluation

def test_metrics_without_labels_say_not_calculable(sample_dirs):
    res = run_pipeline(input_path=sample_dirs["story_labelled"], settings=Settings(provider="none"), top_n=6)
    m = compute_metrics(res.promos, res.episodes)
    assert m["precision@5"] == NC and m["precision@10"] == NC and m["approval_rate"] == NC
    assert "NOT CALCULABLE" in m["gold_recall"]
    assert m["hard_constraints"]["python_validation_passed"].startswith(f"{len(res.promos)}/")


def test_precision_only_from_real_labels(sample_dirs):
    res = run_pipeline(input_path=sample_dirs["story_labelled"], settings=Settings(provider="none"), top_n=6)
    ids = [p.promo_id for p in res.promos]
    assert len(ids) >= 4
    reviews = {ids[0]: {"status": "approved"}, ids[1]: {"status": "rejected"}, ids[2]: {"status": "approved"},
               ids[3]: {"status": "approved"}}
    pk = precision_at_k(res.promos, reviews, ks=(4, 50))
    assert pk["precision@4"] == 0.75
    if len(ids) > 4:
        assert "NOT CALCULABLE" in str(pk["precision@50"])          # not every clip in the top list is labelled
    assert gold_recall(res.promos, [{"episode": res.promos[0].segments[0].episode,
                                     "start": res.promos[0].segments[0].start, "end": res.promos[0].segments[0].end}])["recall"] == 1.0


def test_hard_constraints_catch_bad_promo(sample_dirs):
    res = run_pipeline(input_path=sample_dirs["story_labelled"], settings=Settings(provider="none"), top_n=4)
    bad = res.promos[0].model_copy(deep=True)
    bad.segments[0].end = bad.segments[0].start + 8
    emap = {e.number: e for e in res.episodes}
    hc = hard_constraints([bad], emap)
    assert hc["duration_20_to_60s"].startswith("0/")


def test_public_failure_analysis_has_no_quotes_or_names(sample_dirs, tmp_path):
    res = run_pipeline(input_path=sample_dirs["story_labelled"], out_dir=tmp_path, settings=Settings(provider="none"), top_n=8)
    pub = (tmp_path / "failure_analysis_public_redacted.md").read_text(encoding="utf-8")
    for p in res.promos:
        for t in p.transcript:
            if t["kind"] == "dialogue" and len(t["text"]) > 12:
                assert t["text"] not in pub
    for name in ("Mara", "Elias", "Harrow", "Lena"):
        assert name not in pub


# ---------------------------------------------------------------- doctor / CLI

def test_doctor_module_imports_only_standard_library():
    """doctor must work before `pip install`, so it (and llm_provider) may not import third-party packages."""
    std = set(sys.stdlib_module_names)
    for fname in ("doctor.py", "llm_provider.py"):
        tree = ast.parse((ROOT / "promoforge" / fname).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split(".")[0]]
            for m in mods:
                assert m in std or m == "promoforge", f"{fname} imports non-stdlib module {m}"


def test_doctor_runs_and_is_ascii():
    r = subprocess.run([sys.executable, "-m", "promoforge", "doctor"], cwd=ROOT, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PROMOFORGE_PROVIDER": "none", "HOME": "/tmp"}, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[OK]" in r.stdout
    r.stdout.encode("ascii")                                       # raises if any non-ASCII character slipped in


def test_cli_run_and_evaluate(sample_dirs, tmp_path):
    out = tmp_path / "o"
    r = subprocess.run([sys.executable, "-m", "promoforge", "run", "--input", str(sample_dirs["story_inline"]),
                        "--out", str(out), "--rules-only", "--top-n", "5"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    r2 = subprocess.run([sys.executable, "-m", "promoforge", "evaluate", "--run", str(out)], cwd=ROOT,
                        capture_output=True, text=True, timeout=120)
    assert r2.returncode == 0 and "NOT CALCULABLE" in r2.stdout


def test_gitignore_blocks_private_material():
    g = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for needle in (".env", "submission_private", "*.zip", ".promoforge_cache", "outputs"):
        assert needle in g
