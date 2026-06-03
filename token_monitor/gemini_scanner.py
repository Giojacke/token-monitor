"""
Scanner de Gemini CLI — lee ~/.gemini/tmp/<usuario>/chats/session-*.jsonl

Estrategia de path:
  1. Intenta ~/.gemini/tmp/<username>/chats/  (nombre del usuario del SO)
  2. Fallback: busca cualquier subdirectorio de ~/.gemini/tmp/ que tenga chats/

El JSONL usa un patrón append-update: el mismo mensaje (mismo "id") aparece
varias veces. Se deduplica por id para evitar doble conteo de tokens.
"""

import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import SCAN_INTERVAL
from .parser import parse_gemini_line, calc_gemini_cost
from .state import TokenState, PERIODS


def find_gemini_chats_dir() -> Path | None:
    """
    Encuentra ~/.gemini/tmp/<usuario>/chats/ de forma dinámica.

    Prioriza Path.home().name como nombre del subdirectorio (funciona en
    Windows y Linux/Mac). Si no existe, itera buscando cualquier subdir
    con carpeta chats/ como fallback para entornos corporativos/Docker.
    """
    base = Path.home() / ".gemini" / "tmp"
    if not base.exists():
        return None

    # Intento 1: subdirectorio con el nombre del usuario del SO
    primary = base / Path.home().name / "chats"
    if primary.exists():
        return primary

    # Fallback: busca cualquier subdirectorio que tenga chats/
    for subdir in base.iterdir():
        if subdir.is_dir():
            chats = subdir / "chats"
            if chats.exists():
                return chats

    return None


def _period_starts() -> dict[str, datetime]:
    now   = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "5h":    (now - timedelta(hours=5)).astimezone(timezone.utc),
        "today": today.astimezone(timezone.utc),
        "week":  (today - timedelta(days=today.weekday())).astimezone(timezone.utc),
        "month": today.replace(day=1).astimezone(timezone.utc),
        "year":  today.replace(month=1, day=1).astimezone(timezone.utc),
    }


class GeminiScanner:
    """
    Escanea el directorio de chats de Gemini CLI cada SCAN_INTERVAL segundos.
    La ruta se resuelve dinámicamente en cada ciclo.
    """

    def __init__(self, state: TokenState, stop_event: threading.Event):
        self.state  = state
        self._stop  = stop_event
        self._cache: dict = {}
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan()
            except Exception:
                pass
            time.sleep(SCAN_INTERVAL)

    def _scan(self) -> None:
        chats_dir = find_gemini_chats_dir()
        if chats_dir is None:
            return

        all_files = list(chats_dir.glob("session-*.jsonl"))
        if not all_files:
            all_files = list(chats_dir.glob("*.jsonl"))
        if not all_files:
            return

        starts  = _period_starts()
        current = max(all_files, key=lambda f: f.stat().st_mtime)

        totals: dict[str, dict] = {
            p: {"in": 0, "out": 0, "cached": 0, "req": 0, "cost": 0.0}
            for p in PERIODS
        }
        log: list[str] = []
        last_model: str = ""

        for f in all_files:
            stat = f.stat()
            key  = str(f)
            hit  = self._cache.get(key)

            if hit and hit["mtime"] == stat.st_mtime and hit["size"] == stat.st_size:
                fd = hit["data"]
            else:
                fd = self._read_file(f, starts)
                self._cache[key] = {"mtime": stat.st_mtime, "size": stat.st_size, "data": fd}

            if f == current:
                for k in ("in", "out", "cached", "req", "cost"):
                    totals["sess"][k] += fd["sess"][k]
                log        = fd["log"]
                last_model = fd.get("last_model", "")

            for p in ("5h", "today", "week", "month", "year"):
                for k in ("in", "out", "cached", "req", "cost"):
                    totals[p][k] += fd[p][k]

        self.state.update_gemini(totals, log, last_model)

    def _read_file(self, path: Path, starts: dict[str, datetime]) -> dict:
        fd: dict = {
            p: {"in": 0, "out": 0, "cached": 0, "req": 0, "cost": 0.0}
            for p in PERIODS
        }
        fd["log"]        = []
        fd["last_model"] = ""

        seen_ids: set = set()   # deduplicación: mismo id aparece varias veces

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    r = parse_gemini_line(line)
                    if not r:
                        continue
                    ts, inp, out, cached, model, entry_id = r

                    # El JSONL hace append-updates: misma entrada se repite
                    # con datos adicionales. Procesamos solo la primera aparición.
                    if entry_id and entry_id in seen_ids:
                        continue
                    if entry_id:
                        seen_ids.add(entry_id)

                    cost = calc_gemini_cost(inp, out, cached, model)

                    fd["sess"]["in"]     += inp
                    fd["sess"]["out"]    += out
                    fd["sess"]["cached"] += cached
                    fd["sess"]["req"]    += 1
                    fd["sess"]["cost"]   += cost
                    fd["last_model"]      = model

                    if ts >= starts["today"]:   # solo entradas de hoy
                        fd["log"].append(
                            f"[{ts.astimezone().strftime('%H:%M:%S')}] [gm]"
                            f"  {model}  in={inp + cached:,}  out={out:,}"
                        )

                    for period, start_utc in starts.items():
                        if ts >= start_utc:
                            fd[period]["in"]     += inp
                            fd[period]["out"]    += out
                            fd[period]["cached"] += cached
                            fd[period]["req"]    += 1
                            fd[period]["cost"]   += cost
        except Exception:
            pass
        return fd
