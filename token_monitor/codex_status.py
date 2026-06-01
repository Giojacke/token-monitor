"""
Polling de rate-limits de Codex CLI cada 60 segundos.

Estrategia (en orden de prioridad):
  1. subprocess.run(["codex", "/status"]) — parsea texto de salida
  2. Lee el evento token_count más reciente del JSONL activo como fallback
"""

import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import CODEX_SESSIONS_DIR

POLL_INTERVAL = 60


# ── helpers de tiempo ─────────────────────────────────────────────────────────

def _reset_str(unix_ts: int) -> str:
    if not unix_ts:
        return ""
    try:
        dt  = datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone()
        rem = dt - datetime.now().astimezone()
        if rem.total_seconds() <= 0:
            return "ya reseteo"
        h = int(rem.total_seconds() // 3600)
        m = int((rem.total_seconds() % 3600) // 60)
        return f"reset en {h}h {m}m"
    except Exception:
        return ""


# ── codex /status ─────────────────────────────────────────────────────────────

def _run_codex_status() -> dict | None:
    """
    Intenta: subprocess.run(["codex", "/status"], capture_output=True)
    Parsea la salida buscando:
      "5-hour window: X% used"
      "weekly: X% used"
    Devuelve dict con primary_pct / secondary_pct, o None si falla.
    """
    try:
        result = subprocess.run(
            ["codex", "/status"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        output = result.stdout + result.stderr
        if not output.strip():
            return None

        data: dict = {}

        # "5-hour window: 72% used" o variantes
        m = re.search(r'5.hour\s+window[^0-9]*(\d+(?:\.\d+)?)\s*%', output, re.I)
        if m:
            data["primary_pct"] = float(m.group(1)) / 100

        # "weekly: 45% used" o "weekly limit: 45%"
        m = re.search(r'week(?:ly)?[^0-9]*(\d+(?:\.\d+)?)\s*%', output, re.I)
        if m:
            data["secondary_pct"] = float(m.group(1)) / 100

        # resets_at: "resets in Xh Ym" o timestamp
        m = re.search(r'resets?\s+in\s+(\d+)h\s*(\d+)m', output, re.I)
        if m:
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60
            data["primary_reset_str"] = f"reset en {m.group(1)}h {m.group(2)}m"
            data["primary_resets_at"] = int(datetime.now().timestamp()) + secs

        return data if data else None

    except Exception:
        return None


# ── fallback: leer desde el JSONL más reciente ────────────────────────────────

def _latest_session_file() -> Path | None:
    if not CODEX_SESSIONS_DIR.exists():
        return None
    files = list(CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"))
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def _read_rate_limits_from_jsonl() -> dict | None:
    f = _latest_session_file()
    if not f:
        return None

    last_rl = None
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "event_msg":
                    continue
                payload = obj.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                rl = payload.get("rate_limits") or {}
                if not rl:
                    continue
                pri = rl.get("primary") or {}
                sec = rl.get("secondary") or {}
                last_rl = {
                    "primary_pct":           pri.get("used_percent") or 0.0,
                    "primary_resets_at":     pri.get("resets_at") or 0,
                    "primary_window_min":    pri.get("window_minutes") or 300,
                    "secondary_pct":         sec.get("used_percent") or 0.0,
                    "secondary_resets_at":   sec.get("resets_at") or 0,
                    "secondary_window_min":  sec.get("window_minutes") or 10080,
                    "plan_type":             rl.get("plan_type") or "",
                }
    except Exception:
        pass
    return last_rl


# ── poller ────────────────────────────────────────────────────────────────────

class CodexStatusPoller:
    """
    Hilo de fondo — actualiza los rate-limits de Codex cada POLL_INTERVAL seg.
    Prioridad: codex /status → fallback JSONL.
    Expone los datos vía .limits (thread-safe).
    """

    def __init__(self, stop_event: threading.Event):
        self._stop   = stop_event
        self._lock   = threading.Lock()
        self._data: dict = {}
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    @property
    def limits(self) -> dict:
        with self._lock:
            return dict(self._data)

    def poll_now(self) -> None:
        """Lectura inmediata al arrancar (sin esperar 60s)."""
        self._do_poll()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._do_poll()
            time.sleep(POLL_INTERVAL)

    def _do_poll(self) -> None:
        # 1. Intentar codex /status
        rl = _run_codex_status()

        # 2. Fallback: JSONL
        if not rl:
            rl = _read_rate_limits_from_jsonl()

        if not rl:
            return

        # Añadir strings de reset si no vinieron del /status
        if "primary_reset_str" not in rl:
            rl["primary_reset_str"]   = _reset_str(rl.get("primary_resets_at", 0))
        if "secondary_reset_str" not in rl:
            rl["secondary_reset_str"] = _reset_str(rl.get("secondary_resets_at", 0))

        with self._lock:
            self._data = rl
