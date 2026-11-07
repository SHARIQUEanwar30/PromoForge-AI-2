# Methodology

## What counts as a promo here
20-60 s total, a hook in the first 3 s, an unresolved cliffhanger at the cut, understandable by someone who has not seen the show.
The tool only chooses moments and cut points; no editing, music or overlays.

## Ten dimensions (all heuristic, explainable)

These follow an editor's checklist. The weights are **editorial assumptions and have not been validated** against real editor decisions.

| Dimension | Weight | How it is computed (rules mode) |
|---|---|---|
| hook | .15 | strongest opening beat that *starts* within 3 s of the clip start: accusation/reveal/threat/stakes words, `!`/`?`, short punchy lines, violent action; nothing in 3 s = low |
| cliffhanger | .15 | strongest "unresolved" cue in the last 3 beats (question, interrupted line, threat, reveal, sudden arrival, stakes), plus intensity of the last beats, minus closure/compliance cues. **Look-ahead:** the next ~8 s after the cut are read; an open question that stays unanswered gains a little, and a clearly stronger moment just after a weak ending is penalised ("cut too early"). Script-marked and episode-end signals add a bonus shrunk by the show-level end-signal rate |
| coherence (flow) | .12 | few scene changes, no long dead air, few speakers, enough dialogue; penalties for stitched / cross-episode joins (a larger one when the join is only assumed) |
| standalone | .11 | starts on a line that leans on earlier context, back-references, mid-scene start, names never shown, too many speakers |
| emotion | .10 | emotion labels and words, strongest beats |
| appeal | .10 | variety of angles (power, family, crime, work, romance, revenge, suspense, threat, confrontation, reveal), density of strong beats, turn-taking, quotable line, stakes, relationship words |
| escalation (rising tension) | .09 | intensity rises across thirds / steps, a late peak or twist; flat or repetitive clips score low |
| curiosity | .08 | the clip leaves a specific question open |
| spoiler control | .05 | penalty when the clip contains the resolution or a big reveal late in the episode, or ends with a closing line |
| duration fit | .05 | best at 30-50 s |

In AI mode: for each dimension the AI score is first moved toward the rule scores' average and spread (its own order is kept), then
final = 0.7 x AI + 0.3 x rules. The AI also ranks the clips of each batch (a small +/-0.03 bonus), and confidence drops when AI and rules disagree.
The AI also scans a few episodes at a time for extra strong moments; every such moment is turned into times by Python, validated and scored by the same rules.

## Must-pass gates (AI mode)
An average can hide a fatal flaw, so after blending, any of hook, cliffhanger, clear-alone or spoiler control below 0.60 lowers the rank score
(penalty = how far below 0.60 x 0.4 / 0.4 / 0.3 / 0.5; spoilers weigh most). Found by the first real run: the AI itself said two top-10 clips gave away
the show's secret identity, yet a 5% spoiler weight could not demote them.

## Quality floor
A promo is listed only if its total clears a floor (0.70, relaxed to 85% of the story's best score, never below 0.60) and its hook and
cliffhanger are not weak. At least 6 are always returned. So there can be many promos (up to 60) but no padding.

## Confidence
`high` only when hook >= .60, cliffhanger >= .65, standalone >= .80, coherence >= .60 and at most one risk. `low` when timing is estimated,
hook < .30, cliffhanger < .30 or standalone < .60. Otherwise `medium`.

## Ranking
Greedy selection that subtracts a small penalty for repeating an episode or a main angle, drops near-duplicates (>30% time overlap
in one episode, or >55% word overlap) and caps promos per episode (default 3).

## Evaluation (honest)
* **Always calculable:** hard-constraint pass rates (20-60 s, inside the script's real time range, no mid-line cut, something
  happens in the first 3 s, Python validation).
* **Only from labels:** Precision@K and approval rate (from `reviews.json`, produced by the Editing Desk page); gold recall
  (if gold clips are supplied).
* **Diagnostic only:** AI-vs-rules agreement is agreement between two scorers, not accuracy.
* Everything else prints `NOT CALCULABLE`.

## Known limits
Text-only; English-only cue lists; names are detected heuristically (nationalities can be mistaken for names); a question can look
like a cliffhanger although the next line resolves it; scores in a narrow band are effectively tied.
