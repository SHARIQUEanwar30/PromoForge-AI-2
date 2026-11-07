# Architecture

```
input (ZIP / folder / txt / md / pdf)
   |  ingestion.py   encodings (utf-8-sig, utf-16, cp1252), dedupe, junk skipping, episode numbering
   v
parser.py  ->  Episode -> Scene -> Beat   (4 formats; IDs like E021-S02-B003 are unique across the whole run)
   |
   v
scoring.compute_context     show-level facts (e.g. share of episodes ending with a sting; known names)
   |
   v
candidate_generator.py
   |  every shot-aligned 20-60 s window (never cut inside a dialogue line)  -> non-maximum suppression per episode
   |  + stitched (skip-gap) candidates inside one episode
   |  + cross-episode bridges (only if the next episode's continuity note says it continues directly)
   |  every candidate is validated before it may exist (validator.py)
   v
scoring.py        7 explainable dimensions + confidence + standalone risks
   v
ranking.py        greedy MMR (diversity), near-duplicate removal, per-episode cap, plain-English rank reason
   |
   +--> (optional) story_engine.llm_story    1 call: premise, genre, characters, reveals (from loglines only)
   +--> (optional) llm_judge.judge_promos    batches of 4 candidates, BEAT IDS in / BEAT IDS out
   |         python re-validates: real time range, 20-60 s, shorten-only trims, no mid-line cut,
   |         quoted text must exist in the transcript; any failure -> heuristic scores + visible note
   v
pipeline.py       validate again, export JSON/CSV/report/failure analysis, save/load runs
evaluation.py     hard-constraint pass rates; Precision@K/approval/gold recall ONLY from labels
app.py            Streamlit (6 pages): upload, dashboard, story, promo cards, Editing Desk (full script, + / − 0.5 s, Keep/Skip/Flag; every move re-validated by `promoforge/editing.py`), export (CSV + one `.txt` per promo from `promoforge/export_text.py`)
ui_config.py      ONE file for wording, colours, the AI list (free / not free) and the hidden settings
ui_logic.py       pure helpers: which AI + which key, pop-up reasons, automatic promo count (no Streamlit import)
```

## Key design decisions

1. **The LLM never decides timestamps.** It reasons over beat IDs. Python owns time.
2. **Rules-only always works.** AI improves judgement, it is not a dependency. Failure = fallback + warning.
3. **Swappable provider** through settings only (`llm_provider.py`): Gemini, OpenAI-compatible, Anthropic, Mock. In the app the
   list lives in `ui_config.PROVIDERS`; an AI that is not free shows a "needs your own key" pop-up. For OpenAI and Claude the model
   is chosen automatically from the list the service offers for the key (untested with real paid keys).
   Disk cache (so re-runs are free), rate limiter, call budget, token counting, JSON validation with one repair retry.
4. **Model names are never hard-coded as the only option.** `PROMOFORGE_MODEL` stays empty; for Gemini the tool lists the models
   a key can use, picks from an ordered list, and switches on 404 / "no longer available", recording the switch.
5. **Caches live on objects** (`Episode._features`, `Episode._beats` are Pydantic private attributes), not in global dicts keyed by `id()`.
6. **`doctor` and `llm_provider` import only the standard library** so setup checks work before `pip install` (a test enforces this).

## Cost and volume (measured on a 50-episode, ~75k-word show)

* ~40,000 windows enumerated and scored, ranking included: about 6 seconds on a laptop CPU, no cost.
* AI step: 16 calls and about 24,000 input tokens (characters/4 estimate) with a 60-candidate pool.
