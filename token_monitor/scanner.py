import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import SCAN_INTERVAL, CLAUDE_SESSION_WINDOW_H
from .parser import parse_usage_line, calc_cost
from .state import TokenState, PERIODS


def _period_starts() -> dict[str, datetime]:
    """Calcula el inicio UTC de cada período basado en la hora local actual."""
    now   = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    week_start  = today - timedelta(days=today.weekday())        # lunes de esta semana
    month_start = today.replace(day=1)
    year_start  = today.replace(month=1, day=1)

    return {
        "5h":    (now - timedelta(hours=CLAUDE_SESSION_WINDOW_H)).astimezone(timezone.utc),
        "today": today.astimezone(timezone.utc),
        "week":  week_start.astimezone(timezone.utc),
        "month": month_start.astimezone(timezone.utc),
        "year":  year_start.astimezone(timezone.utc),
    }


class TokenScanner:
    """
    Escanea ~/.claude/projects/**/*.jsonl cada SCAN_INTERVAL segundos.

    Sesión  → archivo principal (no subagente) con mtime más reciente.
    Períodos → today / week / month / year filtrados por timestamp UTC.
    Cache   → evita releer archivos sin cambios (mtime + size).
    """

    def __init__(self, projects_dir: Path, state: TokenState, stop_event: threading.Event):
        self.dir    = projects_dir
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
        all_files = list(self.dir.rglob("*.jsonl"))
        if not all_files:
            return

        starts     = _period_starts()
        main_files = [f for f in all_files if "subagents" not in f.parts]
        current    = max(main_files or all_files, key=lambda f: f.stat().st_mtime)

        # Acumuladores por período
        totals: dict[str, dict] = {
            p: {"in": 0, "out": 0, "cw": 0, "cr": 0, "req": 0, "cost": 0.0}
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

            # Sesión = solo el archivo más reciente
            if f == current:
                for k in ("in", "out", "cw", "cr", "req", "cost"):
                    totals["sess"][k] += fd["sess"][k]
                log        = fd["log"]
                last_model = fd.get("last_model", "")

            # Todos los archivos contribuyen a los períodos de tiempo
            for p in ("5h", "today", "week", "month", "year"):
                for k in ("in", "out", "cw", "cr", "req", "cost"):
                    totals[p][k] += fd[p][k]

        self.state.update(totals, log, last_model)

    def _read_file(self, path: Path, starts: dict[str, datetime]) -> dict:
        fd: dict = {
            p: {"in": 0, "out": 0, "cw": 0, "cr": 0, "req": 0, "cost": 0.0}
            for p in PERIODS
        }
        fd["log"]        = []
        fd["last_model"] = ""

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    r = parse_usage_line(line)
                    if not r:
                        continue
                    ts, inp, out, cache_w, cache_r, model = r
                    cost = calc_cost(inp, out, cache_w, cache_r, model)

                    # Sesión = todos los tokens del archivo (se filtra en _scan)
                    fd["sess"]["in"]   += inp
                    fd["sess"]["out"]  += out
                    fd["sess"]["cw"]   += cache_w
                    fd["sess"]["cr"]   += cache_r
                    fd["sess"]["req"]  += 1
                    fd["sess"]["cost"] += cost
                    fd["last_model"]    = model

                    total_in = inp + cache_w + cache_r
                    short    = model.replace("claude-", "")
                    if ts >= starts["today"]:   # solo entradas de hoy en el log
                        fd["log"].append(
                            f"[{ts.astimezone().strftime('%H:%M:%S')}] [cl]"
                            f"  {short}  in={total_in:,}  out={out:,}"
                        )

                    for period, start_utc in starts.items():
                        if ts >= start_utc:
                            fd[period]["in"]   += inp
                            fd[period]["out"]  += out
                            fd[period]["cw"]   += cache_w
                            fd[period]["cr"]   += cache_r
                            fd[period]["req"]  += 1
                            fd[period]["cost"] += cost
        except Exception:
            pass
        return fd
