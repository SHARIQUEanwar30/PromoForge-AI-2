import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SAMPLES = ROOT / "sample_data"


@pytest.fixture(scope="session")
def sample_dirs():
    if not (SAMPLES / "story_labelled").exists():
        import runpy
        runpy.run_path(str(ROOT / "tools" / "make_sample_data.py"), run_name="__main__")
    return {k: SAMPLES / k for k in ("story_labelled", "story_inline", "story_fountain")}


@pytest.fixture(scope="session")
def labelled(sample_dirs):
    from promoforge.ingestion import load_input
    return load_input(sample_dirs["story_labelled"]).episodes


@pytest.fixture(scope="session")
def ctx_and_map(labelled):
    from promoforge.scoring import compute_context
    return compute_context(labelled), {e.number: e for e in labelled}
