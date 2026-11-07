"""Data models: Beat -> Scene -> Episode, and Promo / Segment / ScoreBreakdown / ValidationReport."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr

BeatKind = Literal["dialogue", "action", "camera", "sound"]
PromoKind = Literal["single", "stitched", "cross_episode"]


def fmt_ts(t: float) -> str:
    """Seconds -> 'mm:ss.xx' (same style as the input pack)."""
    t = max(0.0, float(t))
    m = int(t // 60)
    s = t - 60 * m
    return f"{m:02d}:{s:05.2f}"


class Beat(BaseModel):
    id: str                      # unique across the whole run, e.g. E021-S02-B003
    episode: int
    scene: int
    kind: BeatKind
    speaker: Optional[str] = None
    text: str = ""
    start: float
    end: float
    emotion: Optional[str] = None
    timing_estimated: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class Scene(BaseModel):
    index: int
    heading: str = ""
    start: float = 0.0
    end: float = 0.0
    beats: list[Beat] = Field(default_factory=list)

    @property
    def continuous(self) -> bool:
        return "CONTINUOUS" in self.heading.upper() or "LATER" in self.heading.upper()


class Episode(BaseModel):
    number: int
    logline: str = ""
    continuity: str = ""
    scenes: list[Scene] = Field(default_factory=list)
    duration: float = 0.0
    source: str = ""
    fmt: str = ""
    timing_estimated: bool = False
    warnings: list[str] = Field(default_factory=list)

    # Caches live ON the object (never in global dicts keyed by id()).
    _beats: Optional[list[Beat]] = PrivateAttr(default=None)
    _features: Any = PrivateAttr(default=None)

    def beats(self) -> list[Beat]:
        """All beats of the episode sorted by start time (stable)."""
        if self._beats is None:
            allb = [b for s in self.scenes for b in s.beats]
            self._beats = sorted(allb, key=lambda b: (b.start, b.end))
        return self._beats

    def invalidate(self) -> None:
        self._beats = None
        self._features = None

    def scene(self, index: int) -> Optional[Scene]:
        for s in self.scenes:
            if s.index == index:
                return s
        return None


class Segment(BaseModel):
    episode: int
    start: float
    end: float
    beat_ids: list[str] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def start_ts(self) -> str:
        return fmt_ts(self.start)

    @property
    def end_ts(self) -> str:
        return fmt_ts(self.end)


class ScoreBreakdown(BaseModel):
    hook: float = 0.0
    cliffhanger: float = 0.0
    standalone: float = 0.0
    emotion: float = 0.0
    coherence: float = 0.0
    appeal: float = 0.0
    curiosity: float = 0.0
    escalation: float = 0.0
    spoiler: float = 1.0          # 1.0 = nothing important is given away
    duration_fit: float = 0.0
    total: float = 0.0


class ValidationReport(BaseModel):
    ok: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Promo(BaseModel):
    promo_id: str
    rank: int = 0
    kind: PromoKind = "single"
    segments: list[Segment]
    hook: str = ""
    cliffhanger: str = ""
    why: str = ""
    rank_reason: str = ""
    scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    heuristic_scores: Optional[ScoreBreakdown] = None
    llm_scores: Optional[ScoreBreakdown] = None
    scoring_mode: str = "heuristic"          # "heuristic" or "llm+heuristic"
    confidence: str = "medium"               # low / medium / high
    standalone_risks: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    transcript: list[dict] = Field(default_factory=list)   # rebuilt by Python from the script
    validation: ValidationReport = Field(default_factory=ValidationReport)
    notes: list[str] = Field(default_factory=list)          # warnings from LLM step, trims, etc.
    cut_note: str = ""                                       # plain-words editing tip, e.g. where to cut
    source: str = "rules"                                    # rules / ai_scan (who first proposed this window)

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.segments)
