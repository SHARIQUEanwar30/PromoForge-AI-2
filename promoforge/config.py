"""Weights and thresholds.

IMPORTANT: the scoring weights below are EDITORIAL ASSUMPTIONS. They have not
been validated against real editor decisions. Change them here, in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Ten dimensions taken from an editor's checklist (hook, cliffhanger, coherence, standalone clarity, emotion,
# curiosity, escalation/twist, character+relationship+stakes appeal, spoiler control, pacing/length). Weights follow the
# checklist's ranking of importance; "originality/diversity" is handled by the diversity-aware ranking, not a score.
WEIGHTS = {
    "hook": 0.15,
    "cliffhanger": 0.15,
    "coherence": 0.12,
    "standalone": 0.11,
    "emotion": 0.10,
    "appeal": 0.10,
    "escalation": 0.09,
    "curiosity": 0.08,
    "spoiler": 0.05,
    "duration_fit": 0.05,
}
DIMENSIONS = list(WEIGHTS.keys())

# In LLM mode: final = LLM_BLEND * llm + (1 - LLM_BLEND) * heuristic
LLM_BLEND = 0.7


@dataclass
class Config:
    # Hard rules from the brief
    min_dur: float = 20.0
    max_dur: float = 60.0
    hook_window: float = 3.0
    eps: float = 0.05  # tolerance when comparing times (seconds)

    # Candidate generation
    min_dialogue_beats: int = 2
    per_episode_keep: int = 10
    nms_overlap: float = 0.5
    stitched_seg_min: float = 6.0
    stitched_seg_max: float = 32.0
    stitched_min_gap: float = 4.0
    stitched_top: int = 5
    cross_seg_min: float = 8.0
    cross_seg_max: float = 32.0
    cross_top: int = 4

    # Ranking
    top_n: int = 60
    mmr_episode_penalty: float = 0.06   # per promo already chosen from same episode
    mmr_tag_penalty: float = 0.03       # per promo already chosen with same main angle
    dup_overlap: float = 0.30           # >30% time overlap in same episode = duplicate
    dup_jaccard: float = 0.55           # near-identical wording = duplicate
    max_per_episode: int = 3

    # Look at what comes right AFTER the cut (is the question still open? is the strongest moment cut off?)
    lookahead_s: float = 8.0
    lookahead_beats: int = 2

    # Quality floor for the final list: many promos are allowed, weak ones are not
    quality_min_total: float = 0.70     # composite score a promo needs to be listed (relaxed for weak stories, see quality_floor)
    quality_min_hook: float = 0.35
    quality_min_cliff: float = 0.35
    quality_min_keep: int = 6           # never return fewer than this many (best available)

    # LLM
    llm_pool: int = 60          # how many top heuristic candidates are sent to the judge
    llm_scan_episodes: int = 5  # episodes per "find the best moments" call
    llm_scan_per_episode: int = 2
    llm_batch: int = 4          # candidates per judge call

    # Show-level end-sting shrinking (see scoring.py)
    min_sting_factor: float = 0.15

    # Dialogue timing estimates for formats without timestamps
    est_words_per_sec: float = 2.6
    est_dialogue_pad: float = 0.5
    est_action_pad: float = 1.0
    est_action_words_per_sec: float = 3.5


DEFAULT = Config()
