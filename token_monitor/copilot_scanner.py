"""
Scanner de GitHub Copilot — busca en todos los lugares donde la extensión
de VS Code puede escribir logs o storage con datos de tokens.

Rutas buscadas (Windows):
  %APPDATA%\\GitHub Copilot\\
  %LOCALAPPDATA%\\GitHub Copilot\\
  %APPDATA%\\Code\\User\\globalStorage\\github.copilot\\
  %APPDATA%\\Code\\User\\globalStorage\\github.copilot-chat\\
  %APPDATA%\\Code\\logs\\<sesion>\\exthost\\GitHub.copilot*\\   (logs extensión)
  %APPDATA%\\Code\\logs\\<sesion>\\exthost\\GitHub.copilot-chat*\\

Formatos manejados:
  JSON/JSONL puros
  Archivos .log con líneas "[timestamp] {json}"
  Respuestas OpenAI: usage.prompt_tokens / completion_tokens
  Respuestas Anthropic: usage.input_tokens / output_tokens
  Respuestas Copilot: token_usage.input / output  o  tokens.input / output
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import SCAN_INTERVAL
from .parser import parse_copilot_entry, calc_copilot_cost
from .state import TokenState, PERIODS

# Extensiones de archivo que se escanean
_LOG_EXTS = {".jsonl", ".json", ".log"}

# Regex para extraer JSON de líneas de log con prefijo de timestamp
#   "[2026-06-01 12:34:56.789] {json...}"
_RE_LOG_LINE = re.compile(r"^\[.*?\]\s+(\{.*)")


def _vscode_exthost_copilot_dirs(appdata: str) -> list[Path]:
    """
    Busca los directorios exthost de GitHub Copilot en los logs de VS Code.
    Toma las 5 sesiones más recientes para no leer logs viejos.
    """
    dirs: list[Path] = []
    logs_base = Path(appdata) / "Code" / "logs"
    if not logs_base.exists():
        return dirs
    try:
        sessions = sorted(
            (d for d in logs_base.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime, reverse=True
        )[:5]
    except Exception:
        return dirs
    for session in sessions:
        exthost = session / "exthost"
        if not exthost.exists():
            continue
        try:
            for ext_dir in exthost.iterdir():
                if "copilot" in ext_dir.name.lower() and ext_dir.is_dir():
                    dirs.append(ext_dir)
        except Exception:
            pass
    return dirs


def find_copilot_dirs() -> list[Path]:
    """
    Retorna todos los directorios donde Copilot puede escribir datos.
    Imprime diagnóstico completo en stdout.
    """
    candidates: list[Path] = []
    home = Path.home()

    appdata      = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")

    # ── Windows: Roaming AppData ──────────────────────────────────────────────
    if appdata:
        candidates += [
            Path(appdata) / "GitHub Copilot",
            Path(appdata) / "Code" / "User" / "globalStorage" / "github.copilot",
            Path(appdata) / "Code" / "User" / "globalStorage" / "github.copilot-chat",
        ]
        candidates += _vscode_exthost_copilot_dirs(appdata)

    # ── Windows: Local AppData ────────────────────────────────────────────────
    if localappdata:
        candidates += [
            Path(localappdata) / "GitHub Copilot",
            Path(localappdata) / "Programs" / "GitHub Copilot",
        ]

    # ── Mac ───────────────────────────────────────────────────────────────────
    candidates += [
        home / "Library" / "Application Support" / "GitHub Copilot",
        home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "github.copilot",
        home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "github.copilot-chat",
    ]
    mac_logs = home / "Library" / "Application Support" / "Code" / "logs"
    if mac_logs.exists():
        candidates += _vscode_exthost_copilot_dirs(str(mac_logs.parent.parent))

    # ── Linux ─────────────────────────────────────────────────────────────────
    xdg = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
    candidates += [
        Path(xdg) / "github-copilot",
        home / ".config" / "Code" / "User" / "globalStorage" / "github.copilot",
        home / ".config" / "Code" / "User" / "globalStorage" / "github.copilot-chat",
    ]

    found: list[Path] = []
    for d in candidates:
        exists = d.exists()
        print(f"[copilot] buscando en: {d}  →  {'OK' if exists else 'no existe'}")
        if exists:
            found.append(d)

    if not found:
        print("[copilot] ningún directorio encontrado — Copilot no instalado o ruta desconocida")
    return found


def find_copilot_log_files(dirs: list[Path] | None = None) -> list[Path]:
    """Retorna todos los archivos .json, .jsonl y .log de los directorios de Copilot."""
    if dirs is None:
        dirs = find_copilot_dirs()
    files: list[Path] = []
    for d in dirs:
        try:
            for f in d.rglob("*"):
                if f.is_file() and f.suffix.lower() in _LOG_EXTS:
                    files.append(f)
        except Exception:
            pass
    return files


def _extract_entries_from_text(raw: str, suffix: str) -> list[dict]:
    """
    Extrae objetos dict de texto crudo según el formato del archivo.
    Maneja: JSONL, JSON, archivos .log con prefijo de timestamp.
    """
    entries: list[dict] = []

    if suffix == ".jsonl":
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    entries.append(obj)
            except Exception:
                pass
        return entries

    if suffix == ".log":
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # Intenta extraer JSON de "[timestamp] {json}"
            m = _RE_LOG_LINE.match(line)
            json_str = m.group(1) if m else (line if line.startswith("{") else None)
            if json_str:
                try:
                    obj = json.loads(json_str)
                    if isinstance(obj, dict):
                        entries.append(obj)
                except Exception:
                    pass
        return entries

    # .json — puede ser objeto único, array, o JSONL encubierto
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    entries.append(item)
                    # Si el item tiene sub-listas (e.g. sessions[].exchanges[]), las aplana
                    for v in item.values():
                        if isinstance(v, list):
                            for sub in v:
                                if isinstance(sub, dict):
                                    entries.append(sub)
        elif isinstance(parsed, dict):
            entries.append(parsed)
            # Aplana listas de primer nivel
            for v in parsed.values():
                if isinstance(v, list):
                    for sub in v:
                        if isinstance(sub, dict):
                            entries.append(sub)
    except Exception:
        # Fallback: línea a línea
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    entries.append(obj)
            except Exception:
                pass

    return entries


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
    """

    def __init__(self, state: TokenState, stop_event: threading.Event):
        self.state         = state
        self._stop         = stop_event
        self._cache: dict  = {}
        self._first_scan   = True   # imprime diagnóstico solo en el primer ciclo
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan()
            except Exception:
                pass
            self._first_scan = False
            time.sleep(SCAN_INTERVAL)

    def _scan(self) -> None:
        all_files = find_copilot_log_files()

        if self._first_scan:
            if all_files:
                print(f"[copilot] archivos: {len(all_files)} encontrados")
                for f in all_files:
                    try:
                        size = f.stat().st_size
                        # Muestra las primeras 200 chars para diagnóstico de formato
                        sample = f.read_text(encoding="utf-8", errors="replace")[:200]
                        sample = sample.replace("\n", " ").replace("\r", "")
                        print(f"[copilot]   {f.name} ({size} bytes)  muestra: {sample!r}")
                    except Exception as e:
                        print(f"[copilot]   {f.name} — error leyendo: {e}")
            else:
                print("[copilot] archivos: ninguno encontrado en los directorios OK")

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
            cache_key = str(f)
            hit = self._cache.get(cache_key)

            if hit and hit["mtime"] == stat.st_mtime and hit["size"] == stat.st_size:
                fd = hit["data"]
            else:
                fd = self._read_file(f, starts)
                self._cache[cache_key] = {
                    "mtime": stat.st_mtime, "size": stat.st_size, "data": fd}

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

        entries = _extract_entries_from_text(raw_text, path.suffix.lower())

        if self._first_scan and entries:
            print(f"[copilot]   {path.name}: {len(entries)} entradas JSON")

        try:
            file_mtime_utc = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except Exception:
            file_mtime_utc = datetime.now(timezone.utc)

        parsed_count = 0
        for obj in entries:
            r = parse_copilot_entry(obj, file_mtime_utc)
            if not r:
                continue
            ts, inp, out, cached, model = r
            parsed_count += 1

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

        if self._first_scan and entries:
            print(f"[copilot]   {path.name}: {parsed_count}/{len(entries)} entradas con tokens")

        return fd
