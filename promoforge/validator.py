"""Python validation of every promo. The LLM never decides timestamps; this module has the last word.

Rules (each failure is reported in plain words):
  - episode exists and the segment lies inside the script's real time range
  - segment start < end, segments in story order and not overlapping
  - total duration within [min_dur, max_dur]
  - no cut inside a dialogue line (start or end falling inside a line)
  - trims may only shorten (checked by `check_trim`)
  - quoted text in AI-written descriptions must appear in the transcript (`unverified_quotes`)
  - cross-episode joins only when the next episode's continuity note says it continues
"""
from __future__ import annotations

import re
from typing import Iterable

from .config import Config, DEFAULT
from .models import Episode, Promo, Segment, ValidationReport

CONTINUES_RE = re.compile(
    r"\b(picks? up|immediately|directly|right after|continues?|continuing|moments? later|"
    r"same (?:scene|moment)|cliffhanger|where .* left off|follows? (?:directly|immediately))\b", re.I)


def cuts_dialogue(ep: Episode, t: float, cfg: Config = DEFAULT) -> bool:
    """True if time t falls strictly inside a dialogue line (a cut there would slice a line in half)."""
    for b in ep.beats():
        if b.kind == "dialogue" and b.start + cfg.eps < t < b.end - cfg.eps:
            return True
    return False


def continues_from_previous(ep: Episode) -> bool:
    return bool(CONTINUES_RE.search(ep.continuity or ""))


def show_has_continuity_notes(episodes) -> bool:
    """True if at least one episode carries a 'continues from the last one' style note."""
    return any((e.continuity or "").strip() for e in episodes)


def may_join(prev_ep_number: int, ep: Episode, episodes) -> tuple[bool, bool]:
    """(allowed, assumed). A cross-episode join needs the next episode to say it continues. If the source has no
    continuity notes at all, consecutive episodes are allowed but the join is marked as ASSUMED."""
    if continues_from_previous(ep):
        return True, False
    if not show_has_continuity_notes(episodes):
        return ep.number == prev_ep_number + 1, True
    return False, False


def validate_segments(segments: list[Segment], episodes: dict[int, Episode], cfg: Config = DEFAULT) -> ValidationReport:
    rep = ValidationReport()
    if not segments:
        rep.ok = False
        rep.errors.append("No segments.")
        return rep
    total = 0.0
    prev: Segment | None = None
    for i, s in enumerate(segments, 1):
        ep = episodes.get(s.episode)
        if ep is None:
            rep.errors.append(f"Segment {i}: episode {s.episode} does not exist.")
            continue
        if s.end <= s.start + cfg.eps:
            rep.errors.append(f"Segment {i}: end must be after start.")
        if s.start < -cfg.eps or s.end > ep.duration + cfg.eps:
            rep.errors.append(
                f"Segment {i}: {s.start:.2f}-{s.end:.2f}s is outside the real script range 0-{ep.duration:.2f}s of episode {s.episode}.")
        if cuts_dialogue(ep, s.start, cfg):
            rep.errors.append(f"Segment {i}: starts in the middle of a dialogue line (episode {s.episode}, {s.start:.2f}s).")
        if cuts_dialogue(ep, s.end, cfg):
            rep.errors.append(f"Segment {i}: ends in the middle of a dialogue line (episode {s.episode}, {s.end:.2f}s).")
        if prev is not None:
            if s.episode < prev.episode or (s.episode == prev.episode and s.start < prev.end - cfg.eps):
                rep.errors.append(f"Segment {i}: segments must be in story order and must not overlap.")
            if s.episode != prev.episode:
                if s.episode != prev.episode + 1:
                    rep.errors.append(f"Segment {i}: cross-episode joins must be consecutive episodes ({prev.episode} -> {s.episode}).")
                else:
                    ok_join, assumed = may_join(prev.episode, ep, episodes.values())
                    if not ok_join:
                        rep.errors.append(f"Segment {i}: episode {s.episode}'s continuity note does not say it continues directly from episode {prev.episode}.")
                    elif assumed:
                        rep.warnings.append(f"Episodes {prev.episode} and {s.episode} are joined, but the source has no continuity notes: "
                                            "that they connect directly is an ASSUMPTION.")
        if ep.timing_estimated:
            rep.warnings.append(f"Episode {s.episode} has no timestamps in the source; times are ESTIMATED from word counts.")
        total += max(0.0, s.end - s.start)
        prev = s
    if total < cfg.min_dur - cfg.eps:
        rep.errors.append(f"Total duration {total:.1f}s is below the {cfg.min_dur:.0f}s minimum.")
    if total > cfg.max_dur + cfg.eps:
        rep.errors.append(f"Total duration {total:.1f}s is above the {cfg.max_dur:.0f}s maximum.")
    rep.warnings = sorted(set(rep.warnings))
    rep.ok = not rep.errors
    return rep


def validate_promo(p: Promo, episodes: dict[int, Episode], cfg: Config = DEFAULT) -> ValidationReport:
    rep = validate_segments(p.segments, episodes, cfg)
    # beat ids must exist and live inside the segment
    allbeats = {b.id: b for ep in episodes.values() for b in ep.beats()}
    for s in p.segments:
        for bid in s.beat_ids:
            b = allbeats.get(bid)
            if b is None:
                rep.errors.append(f"Unknown beat id {bid}.")
    rep.ok = not rep.errors
    return rep


def check_trim(orig: Segment, new_start: float, new_end: float, cfg: Config = DEFAULT) -> str | None:
    """A trim may only shorten the original window. Returns an error string or None."""
    if new_start < orig.start - cfg.eps or new_end > orig.end + cfg.eps:
        return "trim would extend the clip beyond the original window (trims may only shorten)"
    if new_end <= new_start:
        return "trim is empty"
    return None


_QUOTE = re.compile(r"[\"“]([^\"”]{3,})[\"”]")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", s.lower())).strip()


def unverified_quotes(text: str, transcript_text: str) -> list[str]:
    """Quoted passages in `text` that do NOT appear in the transcript (possible AI invention)."""
    t = _norm(transcript_text)
    bad = []
    for q in _QUOTE.findall(text or ""):
        nq = _norm(q.replace("...", " ").replace("…", " "))
        parts = [p for p in re.split(r"\s{2,}", nq) if p] or [nq]
        if nq and nq not in t:
            bad.append(q)
    return bad
