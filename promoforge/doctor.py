"""`python -m promoforge doctor`: plain-words setup check.

IMPORTANT: this module (and llm_provider, which it uses) must import ONLY the standard library, so it runs even
when `pip install -r requirements.txt` has not been done yet. Output is ASCII only (Windows consoles).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _ok(msg):
    print("[OK]  " + msg)


def _fix(msg):
    print("[FIX] " + msg)


def _info(msg):
    print("      " + msg)


def main() -> int:
    problems = 0
    print("PromoForge AI - setup check")
    print("-" * 44)

    # 1. Python
    v = sys.version_info
    if v >= (3, 10):
        _ok(f"Python {v.major}.{v.minor}.{v.micro} (3.10 or newer is needed)")
    else:
        problems += 1
        _fix(f"Python {v.major}.{v.minor} is too old. Install Python 3.10+ from python.org and tick 'Add Python to PATH'.")

    # 2. virtual environment hint
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        _ok("A virtual environment (.venv) is active")
    else:
        _info("(tip) No virtual environment is active. That still works, but .venv keeps things tidy.")

    # 3. packages
    needed = {"pydantic": "pydantic", "streamlit": "streamlit", "pandas": "pandas", "pypdf": "pypdf"}
    missing = [pip for mod, pip in needed.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        _ok("All required packages are installed")
    else:
        problems += 1
        _fix("Missing packages: " + ", ".join(missing) + ". Run:  pip install -r requirements.txt")

    # 4. settings / .env
    from promoforge.llm_provider import load_settings, GeminiProvider, make_provider, LLMError, default_http
    s = load_settings()
    if s.env_file_found:
        _ok(f".env file found: {s.env_file_found}")
    else:
        _info("No .env file found. Rules-only mode works without one. For AI mode: copy .env.example to .env and fill it in.")

    print()
    if s.provider in ("none", ""):
        _ok("Provider: none (rules-only mode). The tool works without any AI key.")
        print("\nSummary: " + ("everything needed for rules-only mode is ready." if problems == 0 else f"{problems} thing(s) to fix above."))
        return 0 if problems == 0 else 1

    _ok(f"Provider set to: {s.provider}")
    if s.provider != "mock":
        if s.api_key:
            _ok(f"API key is set: {s.masked_key()}")
        elif s.provider == "openai" and s.base_url and ("localhost" in s.base_url or "127.0.0.1" in s.base_url):
            _info("No API key needed for a local server.")
        else:
            problems += 1
            _fix("PROMOFORGE_API_KEY is empty. Open .env, paste your key after the = sign (no spaces, no quotes), save, run doctor again.")
            print("\nSummary: " + f"{problems} thing(s) to fix above.")
            return 1
    _info("Model setting: " + (s.model if s.model else "(empty = automatic, recommended)"))

    # 5. one tiny real call
    print()
    print("Making one tiny real call to the AI service...")
    try:
        prov = make_provider(s)
        if prov.name == "gemini":
            try:
                names = prov.list_models()
                _ok(f"Your key can use {len(names)} models. Examples: " + ", ".join(names[:6]))
            except LLMError as e:
                _fix(f"Could not list models: {e}")
                problems += 1
                if e.kind == "auth":
                    print("\nSummary: the key was rejected. Create a new key at https://aistudio.google.com/apikey")
                    return 1
        c = prov.generate("Reply with JSON only.", 'Return exactly this JSON: {"ok": true}')
        _ok(f"The AI answered. Model that answered: {c.model or prov.model}")
        for ev in getattr(prov, "events", []):
            _info("note: " + ev)
        if "ok" not in c.text:
            _info("(the answer was unusual, but the connection works): " + c.text[:80].replace("\n", " "))
    except LLMError as e:
        problems += 1
        _fix(f"The AI call failed ({e.kind}): {e}")
        if e.kind == "model_not_found":
            _info("Leave PROMOFORGE_MODEL empty so the tool picks a working model by itself.")
        if e.kind == "network":
            _info("Check your internet connection / VPN / firewall.")
        if e.kind == "quota":
            _info("The free-tier daily quota is used up. Wait until tomorrow or use another provider.")
    print("\nSummary: " + ("all good." if problems == 0 else f"{problems} thing(s) to fix above."))
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
