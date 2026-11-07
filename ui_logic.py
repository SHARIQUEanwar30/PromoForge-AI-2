"""Small pure helpers behind the screen (no Streamlit import, so they are easy to test).

The screen asks: "which AI did the visitor pick, is there a key, what should the pop-up say?"  The answers live here.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import ui_config as C
from promoforge.llm_provider import Settings, load_settings


def provider_by_id(pid: str) -> dict:
    for p in C.PROVIDERS:
        if p["id"] == pid:
            return p
    return C.PROVIDERS[0]


def provider_options() -> list[str]:
    return [p["id"] for p in C.PROVIDERS]


def provider_text(p: dict) -> str:
    return f"{p['icon']}  {p['label']}  ({p['blurb']})"


def auto_top_n(episodes: int) -> int:
    a = C.AUTO
    return int(max(a["min_promos"], min(a["max_promos"], round(a["promos_per_episode"] * max(1, episodes)))))


def site_secrets(secret_getter=None) -> dict:
    """Values the host stored privately (Streamlit Secrets), falling back to real environment variables.

    `secret_getter(name)` is passed by app.py so that this module never imports Streamlit."""
    out = {}
    for name in ("PROMOFORGE_API_KEY", "PROMOFORGE_PROVIDER", "PROMOFORGE_MODEL", "PROMOFORGE_MAX_CALLS", "PROMOFORGE_RPM"):
        v = ""
        if secret_getter:
            try:
                v = str(secret_getter(name) or "")
            except Exception:  # noqa: BLE001  (no secrets file: normal on a laptop)
                v = ""
        out[name] = v.strip().strip("\"'") or os.environ.get(name, "").strip().strip("\"'")
    return out


def resolve(choice_id: str, user_key: str = "", secrets: Optional[dict] = None) -> tuple[Settings, Optional[str]]:
    """Turn the visitor's choice into engine settings.

    Returns (settings, problem). problem is None when we can go, "paid" when a not-free AI needs the visitor's key,
    or "missing" when a free AI needs a key and neither the site nor the visitor has one."""
    secrets = secrets or {}
    p = provider_by_id(choice_id)
    base = load_settings()                                   # .env on a laptop
    mc = secrets.get("PROMOFORGE_MAX_CALLS") or os.environ.get("PROMOFORGE_MAX_CALLS")
    s = Settings(provider=p["provider"], model="", base_url=p.get("base_url", ""),
                 max_calls=int(mc) if mc else C.AUTO["ai_call_budget"],
                 rpm=int(secrets.get("PROMOFORGE_RPM") or base.rpm), cache_dir=base.cache_dir)
    if p["provider"] == "none":
        return s, None
    key = (user_key or "").strip()
    if not key and p["site_key"]:
        site = secrets.get("PROMOFORGE_API_KEY") or base.api_key
        site_provider = (secrets.get("PROMOFORGE_PROVIDER") or base.provider or "gemini").lower()
        if site and site_provider in ("gemini", "google", "none", ""):
            key = site
    if p["site_key"]:
        s.model = secrets.get("PROMOFORGE_MODEL") or base.model      # Gemini: normally empty = automatic
    s.api_key = key
    if not key:
        return s, ("missing" if p["free"] else "paid")
    return s, None


def reset_time_text() -> str:
    """When Gemini's daily free limit resets (midnight Pacific time), shown in India time. Falls back to plain words."""
    try:
        from zoneinfo import ZoneInfo
        pt = ZoneInfo("America/Los_Angeles")
        nxt = (datetime.now(pt) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return nxt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%I:%M %p").lstrip("0") + " India time"
    except Exception:  # noqa: BLE001  (Windows without tzdata)
        return "midnight Pacific time"


def ai_problem(report: dict) -> Optional[str]:
    """Map a finished run to a pop-up reason: 'quota', 'badkey', 'failed' or None (all fine / no AI wanted)."""
    ai = (report or {}).get("ai") or {}
    if ai.get("status") in (None, "off", "ok"):
        return None
    issue = ai.get("issue")
    if issue in ("quota", "rate_limit"):
        return "quota"
    if issue in ("auth", "config"):
        return "badkey"
    return "failed"


def popup_texts(reason: str, p: dict) -> dict:
    """Title, paragraphs and key steps for the pop-up, filled in for provider `p`."""
    T = C.POPUP
    fill = {"label": p["label"], "company": p.get("company", p["label"]), "reset": reset_time_text(),
            "url": p.get("key_url", "")}
    kind = {"paid": "paid", "missing": "missing", "quota": "quota", "badkey": "badkey"}[reason]
    steps_key = "free_key_steps" if p["free"] else "paid_key_steps"
    steps = [s.format(**fill) for s in T[steps_key]] if reason in ("missing", "quota", "paid") else []
    return {"title": T[f"{kind}_title"].format(**fill), "body": [b.format(**fill) for b in T[f"{kind}_body"]],
            "steps": steps, "placeholder": T["key_placeholder"].format(**fill)}
