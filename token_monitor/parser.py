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


def _extract_token_counts(obj: dict) -> tuple[int, int, int]:
    """
    Extrae (inp, out, cached) de un objeto que puede tener cualquiera de los
    formatos que usa GitHub Copilot / OpenAI / Anthropic en sus respuestas.

    Formatos manejados:
      Copilot directo:  token_usage.{input, output, cached}
                        tokens.{input, output, cached}
      OpenAI API:       usage.{prompt_tokens, completion_tokens, cached_tokens}
                        usage.{input_tokens, output_tokens}
      Anthropic API:    usage.{input_tokens, output_tokens, cache_read_input_tokens}
      Campos planos:    prompt_tokens, completion_tokens
      VS Code Chat:     requestTokens, responseTokens, totalTokens (parcial)
    """
    def _i(d: dict, *keys) -> int:
        for k in keys:
            v = d.get(k)
            if v and isinstance(v, (int, float)) and v > 0:
                return int(v)
        return 0

    # Busca en los sub-dicts de uso más comunes
    for usage_key in ("token_usage", "tokens", "usage", "tokenUsage", "token_counts"):
        usage = obj.get(usage_key)
        if not isinstance(usage, dict):
            continue
        inp = _i(usage,
                 "input", "input_tokens", "prompt_tokens",
                 "promptTokens", "inputTokens")
        out = _i(usage,
                 "output", "output_tokens", "completion_tokens",
                 "completionTokens", "outputTokens")
        cached = _i(usage,
                    "cached", "cached_tokens", "cached_input_tokens",
                    "cache_read_input_tokens", "cachedTokens",
                    "cache_creation_input_tokens")
        if inp or out:
            return inp, out, cached

    # Campos planos en el objeto raíz
    inp = _i(obj,
             "prompt_tokens", "promptTokens", "input_tokens", "inputTokens",
             "requestTokens")
    out = _i(obj,
             "completion_tokens", "completionTokens", "output_tokens", "outputTokens",
             "responseTokens")
    cached = _i(obj,
                "cached_tokens", "cachedTokens", "cache_read_input_tokens")

    # VS Code Chat guarda totalTokens sin split — si no hay inp/out, usa total como out
    if not (inp or out):
        total = _i(obj, "totalTokens", "total_tokens")
        if total:
            return 0, total, 0

    return inp, out, cached


def parse_copilot_entry(obj: dict, fallback_ts=None):
    """
    Parsea un objeto JSON/dict de GitHub Copilot.

    Formatos soportados (ver _extract_token_counts para detalle):
      {"model": "gpt-5.1", "token_usage": {"input": N, "output": N}, ...}
      {"model": "claude-sonnet-4.5", "usage": {"prompt_tokens": N, ...}, ...}
      {"model": "gpt-4o", "usage": {"input_tokens": N, "output_tokens": N}, ...}
      {"requestTokens": N, "responseTokens": N, ...}

    Devuelve (ts_utc, inp, out, cached, model) o None.
    """
    if not isinstance(obj, dict):
        return None

    inp, out, cached = _extract_token_counts(obj)
    if not (inp or out or cached):
        return None

    # Modelo — prueba varios campos
    model = (obj.get("model") or obj.get("modelId") or obj.get("model_id")
             or obj.get("engine") or "default")
    if not isinstance(model, str):
        model = "default"

    ts_raw = (obj.get("timestamp") or obj.get("created_at") or obj.get("time")
              or obj.get("created") or obj.get("date") or "")
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
