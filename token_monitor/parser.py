import json
from datetime import datetime, timezone

from .config import (
    CLAUDE_MODELS_PRICES,
    CODEX_MODELS_PRICES,
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


def calc_codex_cost(inp: int, out: int, cached: int,
                    model: str = "default") -> float:
    p = CODEX_MODELS_PRICES.get(model) or CODEX_MODELS_PRICES["default"]
    M = 1_000_000
    return (
        inp    * p["in"]     / M +
        cached * p["cached"] / M +
        out    * p["out"]    / M
    )
