import json
from datetime import datetime, timezone

from .config import (
    CLAUDE_MODELS_PRICES,
    CODEX_MODELS_PRICES,
    GEMINI_MODELS_PRICES,
    COPILOT_MODELS_PRICES,
)


def parse_usage_line(line: str):
    """
    Parsea una línea JSONL de Claude Code.

    Formato real (2025):
      obj["type"] == "assistant"
      obj["message"]["model"]
      obj["message"]["usage"]["input_tokens"]
      obj["message"]["usage"]["cache_creation_input_tokens"]
      obj["message"]["usage"]["cache_read_input_tokens"]
      obj["message"]["usage"]["output_tokens"]

    Devuelve (ts_utc, inp, out, cache_w, cache_r, model) o None.
    """
    if not line.strip():
        return None
    try:
        obj = json.loads(line.strip())
    except Exception:
        return None

    msg = obj.get("message") or {}
    u   = msg.get("usage")
    if not u:
        return None

    inp     = u.get("input_tokens") or 0
    cache_w = u.get("cache_creation_input_tokens") or 0
    cache_r = u.get("cache_read_input_tokens") or 0
    out     = u.get("output_tokens") or 0

    if not (inp or out or cache_w or cache_r):
        return None

    model = msg.get("model") or "default"

    try:
        ts = datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now(timezone.utc)

    return ts, inp, out, cache_w, cache_r, model


def calc_cost(inp: int, out: int, cache_w: int, cache_r: int,
              model: str = "default") -> float:
    p = CLAUDE_MODELS_PRICES.get(model) or CLAUDE_MODELS_PRICES["default"]
    M = 1_000_000
    return (
        inp     * p["in"]      / M +
        cache_w * p["cache_w"] / M +
        cache_r * p["cache_r"] / M +
        out     * p["out"]     / M
    )


def parse_codex_line(line: str):
    """
    Parsea una línea JSONL de Codex CLI.

    Eventos relevantes:
      turn_context  → obj["payload"]["model"]  (nombre del modelo)
      event_msg/token_count → last_token_usage (tokens por request)

    Devuelve:
      ("model", model_str)          para turn_context
      (ts_utc, inp, out, cached)    para token_count
      None                          para todo lo demás
    """
    if not line.strip():
        return None
    try:
        obj = json.loads(line.strip())
    except Exception:
        return None

    # Extrae el modelo del turn_context
    if obj.get("type") == "turn_context":
        model = (obj.get("payload") or {}).get("model") or ""
        if model:
            return ("model", model)
        return None

    if obj.get("type") != "event_msg":
        return None

    payload = obj.get("payload") or {}
    if payload.get("type") != "token_count":
        return None

    u = (payload.get("info") or {}).get("last_token_usage") or {}
    inp    = u.get("input_tokens") or 0
    cached = u.get("cached_input_tokens") or 0
    out    = (u.get("output_tokens") or 0) + (u.get("reasoning_output_tokens") or 0)

    if not (inp or out or cached):
        return None

    try:
        ts = datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now(timezone.utc)

    return ts, inp, out, cached


def parse_gemini_line(line: str):
    """
    Parsea una línea JSONL de Gemini CLI.

    Formato real (~/.gemini/tmp/<user>/chats/session-*.jsonl):
      {"id": "uuid", "type": "gemini", "model": "gemini-3-flash-preview",
       "tokens": {"input": N, "output": N, "cached": N, "thoughts": N, ...},
       "timestamp": "ISO8601"}

    El JSONL hace append-updates: el mismo mensaje (mismo "id") aparece
    varias veces. El scanner deduplica por id usando el valor retornado aquí.
    thoughts se suma a output (razonamiento interno de Gemini).

    Devuelve (ts_utc, inp, out, cached, model, entry_id) o None.
    """
    if not line.strip():
        return None
    try:
        obj = json.loads(line.strip())
    except Exception:
        return None

    if obj.get("type") != "gemini":
        return None

    tokens = obj.get("tokens") or {}
    inp      = tokens.get("input")    or 0
    out      = tokens.get("output")   or 0
    cached   = tokens.get("cached")   or 0
    thoughts = tokens.get("thoughts") or 0

    if not (inp or out or cached or thoughts):
        return None

    model    = obj.get("model")    or "default"
    entry_id = obj.get("id")       or ""
    out     += thoughts   # thoughts cuentan como output

    try:
        ts = datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now(timezone.utc)

    return ts, inp, out, cached, model, entry_id


def calc_gemini_cost(inp: int, out: int, cached: int,
                     model: str = "default") -> float:
    p = GEMINI_MODELS_PRICES.get(model) or GEMINI_MODELS_PRICES["default"]
    M = 1_000_000
    return (
        inp    * p["in"]     / M +
        cached * p["cached"] / M +
        out    * p["out"]    / M
    )


def calc_codex_cost(inp: int, out: int, cached: int,
                    model: str = "default") -> float:
    p = CODEX_MODELS_PRICES.get(model) or CODEX_MODELS_PRICES["default"]
    M = 1_000_000
    return (
        inp    * p["in"]     / M +
        cached * p["cached"] / M +
        out    * p["out"]    / M
    )


def parse_copilot_entry(obj: dict, fallback_ts=None):
    """
    Parsea un objeto JSON/dict de GitHub Copilot.

    Formatos soportados:
      {"model": "gpt-5.1", "token_usage": {"input": N, "output": N, "cached": N}, ...}
      {"model": "claude-sonnet-4.5", "tokens": {"input": N, "output": N}, ...}

    Devuelve (ts_utc, inp, out, cached, model) o None.
    """
    if not isinstance(obj, dict):
        return None

    model = obj.get("model") or "default"

    usage = obj.get("token_usage") or obj.get("tokens") or {}
    if not isinstance(usage, dict):
        return None

    inp    = (usage.get("input")          or usage.get("input_tokens")          or 0)
    out    = (usage.get("output")         or usage.get("output_tokens")         or 0)
    cached = (usage.get("cached")         or usage.get("cached_tokens")
              or usage.get("cached_input_tokens")                               or 0)

    if not (inp or out or cached):
        return None

    ts_raw = (obj.get("timestamp") or obj.get("created_at") or obj.get("time") or "")
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except Exception:
        ts = fallback_ts or datetime.now(timezone.utc)

    return ts, inp, out, cached, model


def calc_copilot_cost(inp: int, out: int, cached: int,
                      model: str = "default") -> float:
    p = COPILOT_MODELS_PRICES.get(model) or COPILOT_MODELS_PRICES["default"]
    M = 1_000_000
    return (
        inp    * p["in"]     / M +
        cached * p["cached"] / M +
        out    * p["out"]    / M
    )
