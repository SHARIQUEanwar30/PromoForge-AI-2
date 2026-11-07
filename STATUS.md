# STATUS / handoff

Last updated: 7 Nov 2026. Deadline for the Kuku submission: Sunday 8 Nov 2026, 5:00 PM IST.

## Done and actually run
| Item | Evidence |
|---|---|
| Four parsers (labelled, inline, Fountain, prose) + PDF compact mode + ZIP/TXT/MD ingestion | pytest (`python -m pytest -q`): 126 tests passed; also SRT / VTT / DOCX input |
| Validator, candidate generation (single, stitched, cross-episode), 10-dimension scoring (look-ahead past the cut, rising tension, spoiler control), quality floor, MMR ranking | tests + full run on the 50-episode pack, Rule-based: 59/59 promos pass validation |
| 50 files uploaded at once, Rule-based | measured about 7 s from "read files" to the finished list on the build machine (a free host will be slower; target was 20 s) |
| LLM layer: Gemini / OpenAI-compatible / Anthropic / Mock, cache, budget, rate limit, JSON repair, Gemini model auto-fallback | tests with the Mock provider and a fake HTTP server |
| OpenAI / Claude: model picked automatically from the service's own model list (no model box in the UI) | tests with a fake HTTP server. **Not tried with real paid keys.** |
| "Free limit finished" detection (quota / rate limit) and the pop-up that explains how to make your own key | tests with the Mock `quota` and `quota_late` modes |
| Judge by beat IDs with Python re-validation; editor-rubric prompt, lines after the cut, rescaling and in-batch ranking; AI "find the best moments" scan checked by Python; call budget plan (about 27 of 30 calls for 50 episodes) | tests with the Mock provider |
| Simple Streamlit app, 6 pages, "What's here" line on each, key pop-up, one Editing Desk page (full script with the promo highlighted, + / − 0.5 s, Keep / Skip / Flag, notes) and one .txt file per promo on Export | headless AppTest tests + Playwright screenshots (`docs/screenshots/`); every page also rendered on the real 50-episode result without errors |
| One settings file for wording, colours, AI list, hidden settings (`ui_config.py`) | tests |
| Generalization on 3 synthetic stories in 3 formats | `docs/generalization_test.md` |
| Honest evaluation (no fake metrics) | `evaluate` command: Precision@K / approval = `NOT CALCULABLE (no labels)` until Keep / Skip choices exist |
| Confidentiality scan | `python tools/confidentiality_scan.py --pack <zip> --repo .` printed PASS |
| 7 Nov 2026: Editing Desk (merged inspection + review), one .txt per promo, Dashboard wording (Hook / Cliffhanger), and a fix so ZIP uploads work in the web app (they used to read 0 episodes) | `tests/test_editing_and_export.py`, `tests/test_app.py`; live headless-browser run on the 50-episode pack |

## NOT yet done (needs the author)
1. **Real-model run on the full pack: DONE once** on 6 Nov 2026 (gemini-3.5-flash-lite, 31 calls, 305 s, 36 promos, all valid). It showed that two spoiler-flagged clips ranked in the top 10; the must-pass gate was added after it. Paid OpenAI / Claude keys were never tried.
2. **Live link.** The app is deployed on Streamlit Community Cloud; put its address in README line 5. Updating the app = upload the changed files to GitHub (steps: `DEPLOY.md`).
3. Free hosting sleeps when idle; the first visit after a pause is slow.
4. No editor labels yet, so no Precision@K. Use Keep / Skip on the Editing Desk page, download `reviews.json` from Export > For developers, run `evaluate`.
5. Walkthrough video, Drive folder, Google Form, name and roll number in the PDF (`--name`, `--roll`).

## Known weaknesses (also in the solution document)
* Mild endings can score as cliffhangers when the script itself marks an episode end; compliance endings were only partly fixed.
* The name check can flag nationality words as "names never introduced".
* Scores in the list span a narrow band; order inside it is close to a tie.
* English-only cue lists; text-only (no audio or visuals); weights are editorial guesses.
* Timing for no-timestamp formats is estimated and every such promo is marked low confidence.
* Gemini mode takes a few minutes on a 50-episode show (about 27 calls at the free-tier rate limit of 10 per minute), so it cannot meet the 20-second target; Rule-based does.

## How to resume
`python -m promoforge doctor` -> `streamlit run app.py` (or `python -m promoforge run --input <pack> --out outputs/run --provider gemini`).
