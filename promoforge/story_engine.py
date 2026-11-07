"""Story understanding. Heuristic (always available) and LLM (optional, one small call for the whole show)."""
from __future__ import annotations

from collections import Counter
from typing import Optional

from .llm_provider import LLMClient, LLMError
from .models import Episode
from .scoring import ShowContext, get_features
from .validator import continues_from_previous

STORY_SYSTEM = ("You are a story analyst for a short-drama (microdrama) studio. Use ONLY the loglines and continuity "
                "notes you are given. Return ONLY one JSON object, no commentary.")


def heuristic_story(episodes: list[Episode], ctx: ShowContext) -> dict:
    speakers: Counter = Counter()
    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    angle_total: Counter = Counter()
    reveal_density: list[tuple[float, int]] = []
    for ep in episodes:
        f = get_features(ep, ctx)
        rev = 0
        for b, tc in zip(f.beats, f.tagcount):
            if b.kind == "dialogue" and b.speaker:
                speakers[b.speaker] += 1
                first_seen.setdefault(b.speaker, ep.number)
                last_seen[b.speaker] = ep.number
            angle_total.update(tc)
            rev += tc.get("reveal", 0)
        reveal_density.append((rev / max(1.0, ep.duration / 60.0), ep.number))
    chars = [{"name": n, "lines": c, "first_episode": first_seen[n], "last_episode": last_seen[n]}
             for n, c in speakers.most_common(8)]
    first = episodes[0] if episodes else None
    return {
        "mode": "heuristic",
        "premise": (first.logline if first and first.logline else "(no logline in the source; rules-only mode cannot infer a premise)"),
        "episodes": len(episodes),
        "main_characters": chars,
        "angle_signals": dict(angle_total.most_common()),
        "reveal_heavy_episodes": [n for _, n in sorted(reveal_density, reverse=True)[:5]],
        "direct_pickups": [e.number for e in episodes if continues_from_previous(e)],
        "end_signal_rate": round(ctx.end_signal_rate, 3),
        "sting_factor": round(ctx.sting_factor, 3),
        "episodes_with_end_signal": ctx.episodes_with_end_signal,
        "timing_estimated": any(e.timing_estimated for e in episodes),
        "notes": ["Heuristic story summary: counts and the first logline only. Use an LLM provider for real story understanding."],
    }


def _story_prompt(episodes: list[Episode]) -> str:
    lines = ["TASK: story", "Summarise this series for someone choosing promo clips.", "",
             "Schema: {\"premise\": str, \"genre\": str, \"tone\": str, "
             "\"main_characters\": [{\"name\": str, \"role\": str}], \"central_conflict\": str, "
             "\"best_promo_angles\": [str], \"major_reveals\": [{\"episode\": int, \"what\": str}], \"audience_hook\": str, "
             "\"secrets_to_protect\": [str]}  (secrets_to_protect = big twists a promo must NOT give away)",
             "", "EPISODES:"]
    for e in episodes:
        lines.append(f"E{e.number}: {e.logline[:260]} | continuity: {e.continuity[:160]}")
    return "\n".join(lines)


def llm_story(client: LLMClient, episodes: list[Episode], heur: dict) -> dict:
    valid = {e.number for e in episodes}

    def check(d: dict) -> Optional[str]:
        if not isinstance(d.get("main_characters", []), list) or not isinstance(d.get("major_reveals", []), list):
            return "main_characters and major_reveals must be lists"
        return None

    try:
        d = client.complete_json("story", STORY_SYSTEM, _story_prompt(episodes),
                                 required=("premise", "main_characters"), check=check)
    except LLMError as e:
        out = dict(heur)
        out["notes"] = out.get("notes", []) + [f"LLM story understanding failed ({e}); showing the heuristic summary."]
        return out
    # drop reveals that point to episodes that do not exist
    d["major_reveals"] = [r for r in d.get("major_reveals", []) if isinstance(r, dict) and r.get("episode") in valid]
    out = dict(heur)
    out.update({"mode": "llm", **{k: d.get(k) for k in ("premise", "genre", "tone", "central_conflict", "audience_hook")},
                "llm_main_characters": d.get("main_characters", []), "best_promo_angles": d.get("best_promo_angles", []),
                "major_reveals": d["major_reveals"],
                "secrets_to_protect": [x for x in (d.get("secrets_to_protect") or []) if isinstance(x, str)][:6]})
    out["notes"] = ["Story summary written by the LLM from loglines and continuity notes only."]
    return out


def story_context_line(story: dict, limit: int = 1100) -> str:
    """A short briefing for the judge: premise, genre, conflict, main characters, best angles, secrets to protect."""
    bits = []
    if story.get("premise"):
        bits.append(f"Premise: {story['premise']}")
    if story.get("genre"):
        bits.append(f"Genre: {story['genre']}.")
    if story.get("central_conflict"):
        bits.append(f"Conflict: {story['central_conflict']}")
    chars = [c.get("name") for c in (story.get("llm_main_characters") or []) if isinstance(c, dict) and c.get("name")]
    if chars:
        bits.append("Main characters: " + ", ".join(chars[:6]) + ".")
    if story.get("best_promo_angles"):
        bits.append("Strong promo angles: " + ", ".join(str(a) for a in story["best_promo_angles"][:5]) + ".")
    if story.get("secrets_to_protect"):
        bits.append("Secrets a promo must NOT give away: " + "; ".join(story["secrets_to_protect"][:5]) + ".")
    return " ".join(bits)[:limit]
