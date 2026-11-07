"""Swappable LLM providers with disk cache, rate limiting, call budget, token counting and JSON repair.

Providers (chosen ONLY through settings / .env, never hard-coded):
  gemini     Google AI Studio (free tier is the default plan)
  openai     any OpenAI-compatible endpoint (Groq, OpenRouter, Ollama, OpenAI...) via PROMOFORGE_BASE_URL
  anthropic  Anthropic Messages API
  mock       deterministic fake model for tests (NOT a real AI)
  none       rules-only mode (no LLM)

Model names change and get retired. PROMOFORGE_MODEL should normally stay EMPTY: for Gemini the tool then asks
your key which models exist (ListModels), picks the first match from an ordered list and, if a call returns
404 / "no longer available", switches to the next model automatically and records the switch.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Ordered backup list. Names come from public docs / third-party trackers in Nov 2026 and may be stale:
# that is exactly why discovery + automatic fallback exist. Update this list (not the code) when needed.
GEMINI_DEFAULT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]


class LLMError(Exception):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind          # auth / model_not_found / rate_limit / quota / server / bad_json / budget / config / network


# ---------------------------------------------------------------- settings

def parse_env_file(path: str | os.PathLike) -> dict[str, str]:
    """Read KEY=VALUE lines. utf-8-sig (Windows Notepad BOM), quotes stripped, empty values ignored."""
    out: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return out
    for raw in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().lstrip("﻿"), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        v = v.strip()
        if v:
            out[k] = v
    return out


@dataclass
class Settings:
    provider: str = "none"
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    max_calls: int = 60
    rpm: int = 10
    cache_dir: str = ".promoforge_cache"
    temperature: float = 0.2
    timeout: int = 120
    env_file_found: Optional[str] = None

    def masked_key(self) -> str:
        k = self.api_key
        return "(not set)" if not k else (k[:4] + "..." + k[-3:] if len(k) > 10 else "***")


def load_settings(env_path: str | os.PathLike | None = None, overrides: dict | None = None) -> Settings:
    """Priority: overrides > real environment variables > .env file."""
    candidates = [Path(env_path)] if env_path else [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    file_vals: dict[str, str] = {}
    found = None
    for c in candidates:
        if c.exists():
            file_vals, found = parse_env_file(c), str(c)
            break

    def get(name: str, default: str = "") -> str:
        v = os.environ.get(name, "").strip().strip("\"'")
        return v or file_vals.get(name, default)

    s = Settings(
        provider=(get("PROMOFORGE_PROVIDER", "none") or "none").lower(),
        api_key=get("PROMOFORGE_API_KEY"),
        model=get("PROMOFORGE_MODEL"),
        base_url=get("PROMOFORGE_BASE_URL"),
        max_calls=int(get("PROMOFORGE_MAX_CALLS", "60") or 60),
        rpm=int(get("PROMOFORGE_RPM", "10") or 10),
        cache_dir=get("PROMOFORGE_CACHE_DIR", ".promoforge_cache"),
        env_file_found=found,
    )
    for k, v in (overrides or {}).items():
        if v not in (None, ""):
            setattr(s, k, v)
    s.provider = {"google": "gemini", "openai-compatible": "openai", "groq": "openai", "openrouter": "openai",
                  "ollama": "openai", "claude": "anthropic", "off": "none", "rules": "none"}.get(s.provider, s.provider)
    return s


# ---------------------------------------------------------------- http

def default_http(url: str, headers: dict, body: Optional[dict], timeout: int, method: str = "POST") -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"Network problem: {type(e).__name__}: {e}", "network") from e


@dataclass
class Completion:
    text: str
    in_tokens: int = 0
    out_tokens: int = 0
    model: str = ""


class Provider:
    name = "base"

    def __init__(self, s: Settings, http: Callable = default_http):
        self.s = s
        self.http = http
        self.model = s.model
        self.events: list[str] = []

    def generate(self, system: str, prompt: str) -> Completion:  # pragma: no cover
        raise NotImplementedError


def _err_text(body: str) -> str:
    try:
        j = json.loads(body)
        e = j.get("error", j)
        return (e.get("message") if isinstance(e, dict) else str(e)) or body[:300]
    except Exception:  # noqa: BLE001
        return body[:300]


# ---------------------------------------------------------------- Gemini

class GeminiProvider(Provider):
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, s: Settings, http: Callable = default_http):
        super().__init__(s, http)
        self.tried: set[str] = set()
        self.discovered = False
        self.available: list[str] = []

    def _headers(self):
        return {"Content-Type": "application/json", "x-goog-api-key": self.s.api_key}

    def list_models(self) -> list[str]:
        status, body = self.http(f"{self.BASE}/models?pageSize=200", self._headers(), None, self.s.timeout, "GET")
        if status in (401, 403) or (status == 400 and "API key" in body):
            raise LLMError("Gemini rejected the API key (" + _err_text(body) + "). Check PROMOFORGE_API_KEY.", "auth")
        if status != 200:
            raise LLMError(f"ListModels failed: HTTP {status}: {_err_text(body)}", "server")
        names = []
        for m in json.loads(body).get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                names.append(m["name"].replace("models/", ""))
        return names

    def _order(self) -> list[str]:
        """Models to try, in order. A model set by the user comes first, then discovered/default ones."""
        order = []
        if self.s.model:
            order.append(self.s.model)
        if self.available:
            pref = [m for m in GEMINI_DEFAULT_MODELS if m in self.available]
            extra = sorted(m for m in self.available if "flash" in m and "image" not in m and "tts" not in m
                           and "live" not in m and "embedding" not in m and m not in pref and "preview" not in m)
            order += pref + extra
        else:
            order += GEMINI_DEFAULT_MODELS
        seen, out = set(), []
        for m in order:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def generate(self, system: str, prompt: str) -> Completion:
        if not self.s.api_key:
            raise LLMError("No API key: set PROMOFORGE_API_KEY in .env", "config")
        if not self.discovered:
            self.discovered = True
            try:
                self.available = self.list_models()
            except LLMError as e:
                if e.kind == "auth":
                    raise
                self.events.append(f"Model discovery unavailable ({e}); using the built-in backup list.")
        last_err = None
        for model in self._order():
            if model in self.tried:
                continue
            try:
                c = self._call(model, system, prompt)
                if self.model and self.model != model:
                    self.events.append(f"Model switched from '{self.model}' to '{model}'.")
                self.model = model
                return c
            except LLMError as e:
                last_err = e
                if e.kind == "model_not_found":
                    self.tried.add(model)
                    self.events.append(f"Model '{model}' is not available ({e}); trying the next one.")
                    continue
                raise
        raise LLMError("No Gemini model worked. Last error: " + str(last_err) +
                       " Run `python -m promoforge doctor` to see which models your key can use.", "model_not_found")

    def _call(self, model: str, system: str, prompt: str) -> Completion:
        url = f"{self.BASE}/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.s.temperature, "responseMimeType": "application/json"},
        }
        for attempt in range(4):
            status, text = self.http(url, self._headers(), body, self.s.timeout)
            if status == 200:
                j = json.loads(text)
                try:
                    parts = j["candidates"][0]["content"]["parts"]
                    out = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                except (KeyError, IndexError):
                    raise LLMError("Gemini returned no text (maybe blocked): " + text[:200], "bad_json")
                u = j.get("usageMetadata", {})
                return Completion(out, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0), model)
            msg = _err_text(text)
            low = msg.lower()
            if status == 404 or "no longer available" in low or "is not found" in low or "not supported for generatecontent" in low:
                raise LLMError(msg[:160], "model_not_found")
            if status in (401, 403):
                raise LLMError("Gemini rejected the API key: " + msg[:160], "auth")
            if status == 429:
                if "perday" in low.replace(" ", "").replace("_", "") or "daily" in low:
                    raise LLMError("Daily free-tier quota used up: " + msg[:160], "quota")
                m = re.search(r"retry(?:Delay)?\D{0,12}(\d+(?:\.\d+)?)\s*s", text)
                time.sleep(min(70.0, float(m.group(1)) + 1 if m else 15.0 * (attempt + 1)))
                continue
            if status >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            raise LLMError(f"Gemini HTTP {status}: {msg[:200]}", "error")
        raise LLMError("Gemini kept returning rate-limit/server errors.", "rate_limit")


# ---------------------------------------------------------------- OpenAI-compatible

class OpenAICompatProvider(Provider):
    name = "openai"

    _SKIP = ("audio", "realtime", "image", "tts", "transcribe", "embedding", "search", "instruct", "moderation",
             "whisper", "dall", "davinci", "babbage", "codex", "computer", "deep-research", "vision")

    def _pick_model(self, base: str, headers: dict) -> None:
        """No model typed: ask the service which models this key can use and take a cheap, recent chat model."""
        status, text = self.http(base + "/models", headers, None, self.s.timeout, "GET")
        if status in (401, 403):
            raise LLMError("API key rejected: " + _err_text(text)[:160], "auth")
        if status != 200:
            raise LLMError(f"Could not list models (HTTP {status}): {_err_text(text)[:160]}", "model_not_found")
        rows = [m for m in json.loads(text).get("data", []) if isinstance(m, dict) and m.get("id")]
        ok = [m for m in rows if m["id"].startswith(("gpt-", "o")) and not any(b in m["id"] for b in self._SKIP)]
        if not ok:
            raise LLMError("This key cannot use any chat model I know how to choose. Ask the provider which model to use.", "model_not_found")
        ok.sort(key=lambda m: (0 if "mini" in m["id"] else 1, 1 if re.search(r"-\d{4}-\d{2}-\d{2}$", m["id"]) else 0,
                               -(m.get("created") or 0)))
        self.s.model = self.model = ok[0]["id"]
        self.events.append(f"Model chosen automatically for this key: {self.s.model}")

    def generate(self, system: str, prompt: str) -> Completion:
        base = (self.s.base_url or "https://api.openai.com/v1").rstrip("/")
        headers = {"Content-Type": "application/json"}
        if self.s.api_key:
            headers["Authorization"] = "Bearer " + self.s.api_key
        if not self.s.model:
            self._pick_model(base, headers)
        body = {"model": self.s.model, "temperature": self.s.temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}}
        for attempt in range(4):
            status, text = self.http(base + "/chat/completions", headers, body, self.s.timeout)
            if status == 200:
                j = json.loads(text)
                u = j.get("usage", {})
                return Completion(j["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0),
                                  u.get("completion_tokens", 0), self.s.model)
            msg = _err_text(text)
            if status == 400 and "response_format" in msg and "response_format" in body:
                body.pop("response_format")
                continue
            if status == 404:
                raise LLMError(msg[:160], "model_not_found")
            if status in (401, 403):
                raise LLMError("API key rejected: " + msg[:160], "auth")
            if status == 429 or status >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            raise LLMError(f"HTTP {status}: {msg[:200]}")
        raise LLMError("Too many rate-limit/server errors.", "rate_limit")


# ---------------------------------------------------------------- Anthropic

class AnthropicProvider(Provider):
    name = "anthropic"

    def _pick_model(self, base: str, headers: dict) -> None:
        """No model typed: ask the service which models this key can use; prefer the cheapest family, newest first."""
        status, text = self.http(base + "/v1/models", headers, None, self.s.timeout, "GET")
        if status in (401, 403):
            raise LLMError("API key rejected: " + _err_text(text)[:160], "auth")
        if status != 200:
            raise LLMError(f"Could not list models (HTTP {status}): {_err_text(text)[:160]}", "model_not_found")
        rows = [m for m in json.loads(text).get("data", []) if isinstance(m, dict) and m.get("id")]
        if not rows:
            raise LLMError("This key cannot use any model I know how to choose.", "model_not_found")
        rows.sort(key=lambda m: str(m.get("created_at", "")), reverse=True)           # newest first
        rows.sort(key=lambda m: 0 if "haiku" in m["id"] else 1 if "sonnet" in m["id"] else 2)  # stable: family order
        self.s.model = self.model = rows[0]["id"]
        self.events.append(f"Model chosen automatically for this key: {self.s.model}")

    def generate(self, system: str, prompt: str) -> Completion:
        if not self.s.api_key:
            raise LLMError("No API key: set PROMOFORGE_API_KEY in .env", "config")
        base = (self.s.base_url or "https://api.anthropic.com").rstrip("/")
        headers = {"Content-Type": "application/json", "x-api-key": self.s.api_key, "anthropic-version": "2023-06-01"}
        if not self.s.model:
            self._pick_model(base, headers)
        body = {"model": self.s.model, "max_tokens": 4096, "temperature": self.s.temperature, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        for attempt in range(4):
            status, text = self.http(base + "/v1/messages", headers, body, self.s.timeout)
            if status == 200:
                j = json.loads(text)
                out = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
                u = j.get("usage", {})
                return Completion(out, u.get("input_tokens", 0), u.get("output_tokens", 0), self.s.model)
            msg = _err_text(text)
            if status == 404:
                raise LLMError(msg[:160], "model_not_found")
            if status in (401, 403):
                raise LLMError("API key rejected: " + msg[:160], "auth")
            if status in (429, 529) or status >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            raise LLMError(f"HTTP {status}: {msg[:200]}")
        raise LLMError("Too many rate-limit/server errors.", "rate_limit")


# ---------------------------------------------------------------- Mock (tests only: NOT a real AI)

class MockProvider(Provider):
    """Deterministic fake model. Modes via PROMOFORGE_MODEL: ok (default), bad_json, bad_ids, fake_quote, trim,
    quota (every call fails like a used-up daily quota), quota_late (first 2 calls work, then quota)."""
    name = "mock"

    def __init__(self, s: Settings, http: Callable = default_http):
        super().__init__(s, http)
        self.model = s.model or "mock-ok"
        self.mode = (s.model or "mock-ok").replace("mock-", "")
        self.calls: list[str] = []

    def generate(self, system: str, prompt: str) -> Completion:
        self.calls.append(prompt[:40])
        if self.mode == "quota" or (self.mode == "quota_late" and len(self.calls) > 2):
            raise LLMError("Daily free-tier quota used up: (mock) GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quota")
        if self.mode == "bad_json" and "REPAIR" not in prompt:
            return Completion("this is not json {", len(prompt) // 4, 5, self.model)
        if "TASK: story" in prompt:
            eps = [int(x) for x in re.findall(r"^E(\d+):", prompt, re.M)]
            out = {"premise": "MOCK premise.", "genre": "mock drama", "tone": "tense",
                   "main_characters": [{"name": "Mock A", "role": "lead"}],
                   "central_conflict": "MOCK conflict.", "best_promo_angles": ["confrontation", "reveal"],
                   "major_reveals": [{"episode": eps[0] if eps else 1, "what": "MOCK reveal"}],
                   "audience_hook": "MOCK hook"}
            return Completion(json.dumps(out), len(prompt) // 4, 120, self.model)
        if "TASK: scan" in prompt:
            out_eps = []
            for block in re.split(r"(?m)^### EPISODE ", prompt)[1:]:
                num = int(re.match(r"(\d+)", block).group(1))
                rows = re.findall(r"(?m)^(E\d+-S\d+-B\d+) \| t=([\d.]+)s", block)
                moments = []
                if rows and self.mode != "no_scan":
                    i0 = len(rows) // 3
                    t0 = float(rows[i0][1])
                    j = next((k for k in range(i0, len(rows)) if float(rows[k][1]) - t0 >= 30.0), len(rows) - 1)
                    moments.append({"start_beat_id": rows[i0][0], "end_beat_id": rows[j][0], "why": "MOCK scan pick"})
                out_eps.append({"episode": num, "moments": moments})
            return Completion(json.dumps({"episodes": out_eps}), len(prompt) // 4, 40 * len(out_eps), self.model)
        results = []
        for block in re.split(r"(?m)^### CANDIDATE ", prompt)[1:]:
            cid = re.match(r"id=(\S+)", block).group(1)
            beat_ids = re.findall(r"(?m)^(E\d+-S\d+-B\d+) \|", block)
            h = int(hashlib.md5(cid.encode()).hexdigest()[:6], 16)
            base = 0.35 + (h % 50) / 100.0
            r = {"id": cid,
                 "scores": {k: round(min(1.0, max(0.0, base + d)), 2) for k, d in
                            [("hook", 0.05), ("cliffhanger", 0.0), ("standalone", -0.05), ("emotion", 0.02),
                             ("coherence", 0.03), ("appeal", 0.0), ("curiosity", 0.02), ("escalation", -0.02),
                             ("spoiler", 0.1)]},
                 "hook_beat_id": beat_ids[0] if beat_ids else None,
                 "cliffhanger_beat_id": beat_ids[-1] if beat_ids else None,
                 "why": "MOCK: strong opening line and an unresolved ending.",
                 "standalone_risks": ["MOCK risk"], "start_beat_id": None, "end_beat_id": None, "verdict": "keep"}
            if self.mode == "bad_ids":
                r["hook_beat_id"], r["cliffhanger_beat_id"], r["start_beat_id"] = "E999-S01-B001", "NOPE", "E999-S09-B009"
            if self.mode == "fake_quote":
                r["why"] = 'MOCK: the line "this sentence is never spoken anywhere" is the hook.'
            if self.mode == "trim" and len(beat_ids) > 6:
                r["start_beat_id"] = beat_ids[1]
                r["end_beat_id"] = beat_ids[-2]
            results.append(r)
        order = sorted(range(len(results)), key=lambda i: -results[i]["scores"]["hook"])
        for rk, i in enumerate(order, 1):
            results[i]["rank"] = rk
        return Completion(json.dumps({"results": results}), len(prompt) // 4, 60 * len(results), self.model)


def make_provider(s: Settings, http: Callable = default_http) -> Optional[Provider]:
    p = s.provider
    if p in ("none", ""):
        return None
    if p == "gemini":
        return GeminiProvider(s, http)
    if p == "openai":
        return OpenAICompatProvider(s, http)
    if p == "anthropic":
        return AnthropicProvider(s, http)
    if p == "mock":
        return MockProvider(s, http)
    raise LLMError(f"Unknown provider '{p}'. Use gemini, openai, anthropic, mock or none.", "config")


# ---------------------------------------------------------------- client

def extract_json(text: str):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            return json.loads(t[a:b + 1])
        raise


class LLMClient:
    """Cache + rate limit + budget + token counting + JSON validation (one repair retry)."""

    def __init__(self, settings: Settings, provider: Optional[Provider] = None, sleep: Callable = time.sleep):
        self.s = settings
        self.provider = provider or make_provider(settings)
        if self.provider is None:
            raise LLMError("No LLM provider configured (rules-only mode).", "config")
        self.sleep = sleep
        self.calls = 0
        self.cache_hits = 0
        self.in_tokens = 0
        self.out_tokens = 0
        self.warnings: list[str] = []
        self._last_call = 0.0
        self.cache_dir = Path(settings.cache_dir)

    # -- cache
    def _key(self, task: str, system: str, prompt: str) -> str:
        raw = "\n".join([self.provider.name, self.s.model, task, system, prompt])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str):
        f = self.cache_dir / f"{key}.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
        return None

    def _cache_put(self, key: str, data: dict, model: str):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.json").write_text(json.dumps({"data": data, "model": model}), encoding="utf-8")
        except OSError as e:
            self.warnings.append(f"Could not write cache: {e}")

    def _throttle(self):
        gap = 60.0 / max(1, self.s.rpm)
        wait = self._last_call + gap - time.time()
        if wait > 0:
            self.sleep(wait)

    def _raw_call(self, system: str, prompt: str) -> Completion:
        if self.calls >= self.s.max_calls:
            raise LLMError(f"Call budget reached ({self.s.max_calls} calls). Raise PROMOFORGE_MAX_CALLS to continue.", "budget")
        self._throttle()
        self.calls += 1
        c = self.provider.generate(system, prompt)
        self._last_call = time.time()
        self.in_tokens += c.in_tokens or len(prompt) // 4
        self.out_tokens += c.out_tokens or len(c.text) // 4
        return c

    def complete_json(self, task: str, system: str, prompt: str, required: tuple[str, ...] = (),
                      check: Optional[Callable[[dict], Optional[str]]] = None) -> dict:
        key = self._key(task, system, prompt)
        hit = self._cache_get(key)
        if hit is not None:
            self.cache_hits += 1
            return hit["data"]
        c = self._raw_call(system, prompt)
        err = None
        for attempt in range(2):
            try:
                data = extract_json(c.text)
                if not isinstance(data, dict):
                    raise ValueError("top level must be a JSON object")
                missing = [k for k in required if k not in data]
                if missing:
                    raise ValueError("missing keys: " + ", ".join(missing))
                if check:
                    msg = check(data)
                    if msg:
                        raise ValueError(msg)
                self._cache_put(key, data, c.model)
                return data
            except (ValueError, json.JSONDecodeError) as e:
                err = str(e)
                if attempt == 1:
                    break
                repair = (f"REPAIR: your previous answer was invalid ({err}). Return ONLY a valid JSON object that follows "
                          f"the schema from the original task. Original task:\n{prompt}\n\nPrevious answer:\n{c.text[:2000]}")
                c = self._raw_call(system, repair)
        raise LLMError(f"Model returned invalid JSON twice ({err}).", "bad_json")

    def summary(self) -> dict:
        return {
            "provider": self.provider.name,
            "model_requested": self.s.model or "(auto)",
            "model_used": getattr(self.provider, "model", "") or "",
            "calls_made": self.calls, "cache_hits": self.cache_hits, "call_budget": self.s.max_calls,
            "input_tokens_approx": self.in_tokens, "output_tokens_approx": self.out_tokens,
            "events": list(getattr(self.provider, "events", [])) + self.warnings,
        }
