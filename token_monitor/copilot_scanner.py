"""
Scanner de GitHub Copilot — lee JSON/JSONL de:
  Windows:
    %APPDATA%\\GitHub Copilot\\
    %APPDATA%\\Code\\User\\globalStorage\\github.copilot-chat\\
  Mac:
    ~/Library/Application Support/GitHub Copilot/
    ~/Library/Application Support/Code/User/globalStorage/github.copilot-chat/
  Linux:
    ~/.config/github-copilot/
    ~/.config/Code/User/globalStorage/github.copilot-chat/

Formatos de entrada esperados:
  {"model": "gpt-5.1", "token_usage": {"input": N, "output": N, "cached": N}, ...}
  {"model": "claude-sonnet-4.5", "tokens": {"input": N, "output": N}, ...}
"""

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import SCAN_INTERVAL
from .parser import parse_copilot_entry, calc_copilot_cost
from .state import TokenState, PERIODS


def find_copilot_dirs() -> list[Path]:
    """
    Retorna los directorios donde GitHub Copilot escribe logs.
    Soporta Windows, Mac y Linux. Filtra los que existen.
    """
    dirs: list[Path] = []
    home = Path.home()

    # Windows
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs += [
            Path(appdata) / "GitHub Copilot",
            Path(appdata) / "Code" / "User" / "globalStorage" / "github.copilot-chat",
        ]

    # Mac
    dirs += [
        home / "Library" / "Application Support" / "GitHub Copilot",
        home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "github.copilot-chat",
    ]

    # Linux
    xdg = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
    dirs += [
        Path(xdg) / "github-copilot",
        home / ".config" / "Code" / "User" / "globalStorage" / "github.copilot-chat",
    ]

    return [d for d in dirs if d.exists()]


def find_copilot_log_files(dirs: list[Path] | None = None) -> list[Path]:
    """Retorna todos los archivos .json y .jsonl de los directorios de Copilot."""
    if dirs is None:
        dirs = find_copilot_dirs()
    files: list[Path] = []
    for d in dirs:
        files += list(d.rglob("*.jsonl"))
        files += list(d.rglob("*.json"))
    return files


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


class CopilotScanner:
    """
    Escanea los directorios de GitHub Copilot cada SCAN_INTERVAL segundos.
    Lee tanto archivos .json como .jsonl. Los directorios se re-detectan
    en cada ciclo para soportar instalaciones en caliente.
    """

    def __init__(self, state: TokenState, stop_event: threading.Event):
        self.state   = state
        self._stop   = stop_event
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
        all_files = find_copilot_log_files()
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
            try:
                stat = f.stat()
            except Exception:
                continue
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

        self.state.update_copilot(totals, log[-40:], last_model)

    def _read_file(self, path: Path, starts: dict[str, datetime]) -> dict:
        fd: dict = {
            p: {"in": 0, "out": 0, "cached": 0, "req": 0, "cost": 0.0}
            for p in PERIODS
        }
        fd["log"]        = []
        fd["last_model"] = ""

        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return fd

        # Construye lista de objetos según extensión
        entries: list[dict] = []
        if path.suffix == ".jsonl":
            for line in raw_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        entries.append(obj)
                except Exception:
                    pass
        else:
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, list):
                    entries = [e for e in parsed if isinstance(e, dict)]
                elif isinstance(parsed, dict):
                    entries = [parsed]
            except Exception:
                # Fallback: intenta línea a línea
                for line in raw_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            entries.append(obj)
                    except Exception:
                        pass

        try:
            file_mtime_utc = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except Exception:
            file_mtime_utc = datetime.now(timezone.utc)

        for obj in entries:
            r = parse_copilot_entry(obj, file_mtime_utc)
            if not r:
                continue
            ts, inp, out, cached, model = r

            cost = calc_copilot_cost(inp, out, cached, model)

            fd["sess"]["in"]     += inp
            fd["sess"]["out"]    += out
            fd["sess"]["cached"] += cached
            fd["sess"]["req"]    += 1
            fd["sess"]["cost"]   += cost
            fd["last_model"]      = model

            if ts >= starts["today"]:
                fd["log"].append(
                    f"[{ts.astimezone().strftime('%H:%M:%S')}] [cp]"
                    f"  {model}  in={inp + cached:,}  out={out:,}"
                )

            for period, start_utc in starts.items():
                if ts >= start_utc:
                    fd[period]["in"]     += inp
                    fd[period]["out"]    += out
                    fd[period]["cached"] += cached
                    fd[period]["req"]    += 1
                    fd[period]["cost"]   += cost

        return fd
