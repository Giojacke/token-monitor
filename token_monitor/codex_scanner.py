"""
Scanner de Codex CLI — lee ~/.codex/sessions/**/*.jsonl

Mismo enfoque que TokenScanner (Claude):
  - Filtra períodos por timestamp UTC dentro de cada archivo
  - NO usa la estructura de directorios para filtrar fechas
    (un session file puede empezar un día y tener eventos del siguiente)

Sesión  → archivo rollout con mtime más reciente.
Cache   → evita releer archivos sin cambios (mtime + size).
"""

import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import SCAN_INTERVAL
from .parser import parse_codex_line, calc_codex_cost
from .state import TokenState, PERIODS


def _codex_period_starts() -> dict[str, datetime]:
    """Inicio UTC de cada período (igual que Claude scanner)."""
    now   = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    week_start  = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start  = today.replace(month=1, day=1)

    return {
        "5h":    (now - timedelta(hours=5)).astimezone(timezone.utc),
        "today": today.astimezone(timezone.utc),
        "week":  week_start.astimezone(timezone.utc),
        "month": month_start.astimezone(timezone.utc),
        "year":  year_start.astimezone(timezone.utc),
    }


class CodexScanner:
    """
    Escanea ~/.codex/sessions/**/*.jsonl cada SCAN_INTERVAL segundos.
    Filtra períodos por timestamp UTC del evento (no por carpeta del día).
    """

    def __init__(self, sessions_dir: Path, state: TokenState, stop_event: threading.Event):
        self.dir    = sessions_dir
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
        if not self.dir.exists():
            return

        all_files = list(self.dir.rglob("rollout-*.jsonl"))
        if not all_files:
            return

        starts  = _codex_period_starts()
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

            # Sesión = archivo más reciente
            if f == current:
                for k in ("in", "out", "cached", "req", "cost"):
                    totals["sess"][k] += fd["sess"][k]
                log        = fd["log"]
                last_model = fd.get("last_model", "")

            # Todos los archivos contribuyen a los períodos de tiempo
            for p in ("5h", "today", "week", "month", "year"):
                for k in ("in", "out", "cached", "req", "cost"):
                    totals[p][k] += fd[p][k]

        self.state.update_codex(totals, log, last_model)

    def _read_file(self, path: Path, starts: dict[str, datetime]) -> dict:
        fd: dict = {
            p: {"in": 0, "out": 0, "cached": 0, "req": 0, "cost": 0.0}
            for p in PERIODS
        }
        fd["log"]        = []
        fd["last_model"] = ""
        current_model    = "default"

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    r = parse_codex_line(line)
                    if not r:
                        continue

                    # turn_context → actualiza el modelo activo
                    if isinstance(r, tuple) and len(r) == 2 and r[0] == "model":
                        current_model    = r[1]
                        fd["last_model"] = current_model
                        continue

                    ts, inp, out, cached = r
                    cost = calc_codex_cost(inp, out, cached, current_model)

                    fd["sess"]["in"]     += inp
                    fd["sess"]["out"]    += out
                    fd["sess"]["cached"] += cached
                    fd["sess"]["req"]    += 1
                    fd["sess"]["cost"]   += cost

                    if ts >= starts["today"]:   # solo entradas de hoy
                        fd["log"].append(
                            f"[{ts.astimezone().strftime('%H:%M:%S')}] [cx]"
                            f"  {current_model}  in={inp + cached:,}  out={out:,}"
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
