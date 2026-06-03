"""
Scanner de GitHub Copilot.

Rutas buscadas (Windows):
  %APPDATA%\\Code\\logs\\<sesion>\\window*\\exthost\\GitHub.copilot*\\  ← logs VS Code
  %APPDATA%\\Code\\User\\globalStorage\\github.copilot(-chat)\\          ← storage JSON/JSONL
  %APPDATA%\\GitHub Copilot\\, %LOCALAPPDATA%\\GitHub Copilot\\           ← app standalone

Formatos manejados:
  VS Code plain-text log: "YYYY-MM-DD HH:MM:SS.mmm [level] [fetchCompletions/Chat] ... 200"
    → cuenta requests exitosos; sin token data disponible
  JSON/JSONL con token_usage / usage / tokens
    → extrae in/out/cached tokens cuando están presentes
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

_LOG_EXTS = {".jsonl", ".json", ".log"}

# Regex para extraer JSON de líneas "[timestamp] {json}" (formato antiguo de logs)
_RE_JSON_IN_LOG = re.compile(r"^\[.*?\]\s+(\{.*)")

# VS Code plain-text log formato 1: [fetchCompletions] (inline code completions)
# "2026-05-30 22:36:30.347 [info] [fetchCompletions] Request ... finished with 200"
_RE_VSCODE_FETCH = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    r" \[\w+\] \[fetch\w*\] Request \S+ at "
    r"<https://[^>]+/(?:engines/([^/]+)/)?(\w+)>"
    r" finished with (\d+)"
)

# VS Code plain-text log formato 2: ccreq (chat, edits, agent)
# "2026-06-02 13:56:59.204 [info] ccreq:1e38187e.copilotmd | success | gpt-4o-mini | 986ms | [panel/editAgent]"
_RE_VSCODE_CCREQ = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    r" \[\w+\] ccreq:[a-f0-9]+\.\w+ \| success \| ([^|]+) \| \d+ms \| \[([^\]]+)\]"
)


def _is_vscode_plain_log(first_line: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", first_line.lstrip()))


def _clean_model(raw: str) -> str:
    """Normaliza nombre de modelo: quita sufijo -copilot, toma parte post-arrow si existe."""
    raw = raw.strip()
    if " -> " in raw:
        raw = raw.split(" -> ", 1)[1].strip()
    return raw.replace("-copilot", "").replace("copilot-", "") or "gpt-4o"


def _parse_vscode_plain_log_entries(raw: str) -> list[tuple]:
    """
    Parsea logs planos de VS Code buscando requests Copilot exitosos.
    Captura dos formatos:
      - [fetchCompletions] finished with 200  → inline completions ("comp")
      - ccreq:ID | success | model | Xms | [source]  → chat/edits/agent ("chat")
    Retorna lista de (ts_utc, inp=0, out=0, cached=0, model, req_type).
    """
    entries: list[tuple] = []
    for line in raw.splitlines():
        stripped = line.strip()

        m = _RE_VSCODE_FETCH.match(stripped)
        if m:
            ts_str, model_url, endpoint, status = m.group(1), m.group(2) or "", m.group(3) or "", m.group(4)
            if status == "200":
                try:
                    ts = datetime.fromisoformat(ts_str.replace(" ", "T")).astimezone(timezone.utc)
                except Exception:
                    ts = datetime.now(timezone.utc)
                model = _clean_model(model_url or endpoint)
                entries.append((ts, 0, 0, 0, model, "comp"))
            continue

        m = _RE_VSCODE_CCREQ.match(stripped)
        if m:
            ts_str, model_raw = m.group(1), m.group(2)
            try:
                ts = datetime.fromisoformat(ts_str.replace(" ", "T")).astimezone(timezone.utc)
            except Exception:
                ts = datetime.now(timezone.utc)
            model = _clean_model(model_raw)
            entries.append((ts, 0, 0, 0, model, "chat"))

    return entries


def _vscode_exthost_copilot_dirs(logs_dir: str) -> list[Path]:
    """
    Busca directorios GitHub.copilot* en:
      <logs_dir>/<session>/exthost/          (VS Code clásico)
      <logs_dir>/<session>/window*/exthost/  (VS Code >= 1.85)
    Toma las 5 sesiones más recientes.
    """
    dirs: list[Path] = []
    logs_base = Path(logs_dir)
    if not logs_base.exists():
        return dirs
    try:
        sessions = sorted(
            (d for d in logs_base.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime, reverse=True,
        )[:5]
    except Exception:
        return dirs

    for session in sessions:
        # Candidatos a exthost: session/exthost + session/window*/exthost
        parents = [session]
        try:
            for child in session.iterdir():
                if child.is_dir() and re.match(r"^window\d*$", child.name):
                    parents.append(child)
        except Exception:
            pass

        for parent in parents:
            exthost = parent / "exthost"
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
    """Retorna los directorios donde Copilot puede escribir datos (sin prints)."""
    candidates: list[Path] = []
    home = Path.home()
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")

    if appdata:
        candidates += [
            Path(appdata) / "GitHub Copilot",
            Path(appdata) / "Code" / "User" / "globalStorage" / "github.copilot",
            Path(appdata) / "Code" / "User" / "globalStorage" / "github.copilot-chat",
        ]
        candidates += _vscode_exthost_copilot_dirs(str(Path(appdata) / "Code" / "logs"))

    if localappdata:
        candidates += [
            Path(localappdata) / "GitHub Copilot",
            Path(localappdata) / "Programs" / "GitHub Copilot",
        ]

    candidates += [
        home / "Library" / "Application Support" / "GitHub Copilot",
        home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "github.copilot",
        home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "github.copilot-chat",
    ]
    candidates += _vscode_exthost_copilot_dirs(
        str(home / "Library" / "Application Support" / "Code" / "logs")
    )

    xdg = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
    candidates += [
        Path(xdg) / "github-copilot",
        home / ".config" / "Code" / "User" / "globalStorage" / "github.copilot",
        home / ".config" / "Code" / "User" / "globalStorage" / "github.copilot-chat",
    ]
    candidates += _vscode_exthost_copilot_dirs(str(home / ".config" / "Code" / "logs"))

    # Deduplica y filtra solo los existentes
    seen: set[Path] = set()
    found: list[Path] = []
    for d in candidates:
        if d not in seen and d.exists():
            seen.add(d)
            found.append(d)
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
    """Extrae objetos dict de texto crudo según formato del archivo (JSON/JSONL/log con JSON)."""
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
            m = _RE_JSON_IN_LOG.match(line)
            json_str = m.group(1) if m else (line if line.startswith("{") else None)
            if json_str:
                try:
                    obj = json.loads(json_str)
                    if isinstance(obj, dict):
                        entries.append(obj)
                except Exception:
                    pass
        return entries

    # .json — objeto único, array, o JSONL encubierto
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    entries.append(item)
                    for v in item.values():
                        if isinstance(v, list):
                            for sub in v:
                                if isinstance(sub, dict):
                                    entries.append(sub)
        elif isinstance(parsed, dict):
            entries.append(parsed)
            for v in parsed.values():
                if isinstance(v, list):
                    for sub in v:
                        if isinstance(sub, dict):
                            entries.append(sub)
    except Exception:
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
    Los directorios se descubren una sola vez y se cachean para evitar spam de prints.
    """

    def __init__(self, state: TokenState, stop_event: threading.Event):
        self.state         = state
        self._stop         = stop_event
        self._cache: dict  = {}
        self._dirs: list[Path] | None = None   # se descubre una vez en el primer scan
        self._first_scan   = True
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
        # Descubrir directorios solo la primera vez
        if self._dirs is None:
            self._dirs = find_copilot_dirs()
            if self._first_scan:
                if self._dirs:
                    print(f"[copilot] directorios encontrados: {len(self._dirs)}")
                    for d in self._dirs:
                        print(f"[copilot]   {d}")
                else:
                    print("[copilot] ningún directorio encontrado — Copilot no instalado o ruta desconocida")

        all_files = find_copilot_log_files(self._dirs)

        if self._first_scan:
            if all_files:
                print(f"[copilot] archivos: {len(all_files)} encontrados")
                for f in all_files:
                    try:
                        size = f.stat().st_size
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
            p: {"in": 0, "out": 0, "cached": 0, "req": 0, "chat_req": 0, "comp_req": 0, "cost": 0.0}
            for p in PERIODS
        }
        log: list[str] = []
        last_model: str = ""

        _all_keys = ("in", "out", "cached", "req", "chat_req", "comp_req", "cost")

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
                for k in _all_keys:
                    totals["sess"][k] += fd["sess"].get(k, 0)
                log        = fd["log"]
                last_model = fd.get("last_model", "")

            for p in ("5h", "today", "week", "month", "year"):
                for k in _all_keys:
                    totals[p][k] += fd[p].get(k, 0)

        self.state.update_copilot(totals, log, last_model)

    def _read_file(self, path: Path, starts: dict[str, datetime]) -> dict:
        fd: dict = {
            p: {"in": 0, "out": 0, "cached": 0, "req": 0, "chat_req": 0, "comp_req": 0, "cost": 0.0}
            for p in PERIODS
        }
        fd["log"]        = []
        fd["last_model"] = ""

        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return fd

        # Detectar si es log plano de VS Code (YYYY-MM-DD HH:MM:SS.mmm [level] ...)
        first_line = (raw_text.lstrip() + "\n").split("\n", 1)[0]
        if _is_vscode_plain_log(first_line):
            parsed_entries = _parse_vscode_plain_log_entries(raw_text)
            if self._first_scan:
                chats = sum(1 for e in parsed_entries if len(e) > 5 and e[5] == "chat")
                comps = sum(1 for e in parsed_entries if len(e) > 5 and e[5] == "comp")
                print(f"[copilot]   {path.name}: {comps} inline + {chats} chat (log VS Code — sin tokens)")
        else:
            json_objs = _extract_entries_from_text(raw_text, path.suffix.lower())
            try:
                file_mtime_utc = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except Exception:
                file_mtime_utc = datetime.now(timezone.utc)
            parsed_entries = []
            for obj in json_objs:
                r = parse_copilot_entry(obj, file_mtime_utc)
                if r:
                    parsed_entries.append(r)
            if self._first_scan and json_objs:
                print(f"[copilot]   {path.name}: {len(parsed_entries)}/{len(json_objs)} entradas con tokens")

        for entry in parsed_entries:
            ts, inp, out, cached, model = entry[0], entry[1], entry[2], entry[3], entry[4]
            req_type = entry[5] if len(entry) > 5 else "comp"
            cost = calc_copilot_cost(inp, out, cached, model)

            fd["sess"]["in"]       += inp
            fd["sess"]["out"]      += out
            fd["sess"]["cached"]   += cached
            fd["sess"]["req"]      += 1
            fd["sess"]["chat_req"] += 1 if req_type == "chat" else 0
            fd["sess"]["comp_req"] += 1 if req_type == "comp" else 0
            fd["sess"]["cost"]     += cost
            fd["last_model"]        = model

            if ts >= starts["today"]:
                tag = "ch" if req_type == "chat" else "cp"
                if inp or out:
                    fd["log"].append(
                        f"[{ts.astimezone().strftime('%H:%M:%S')}] [{tag}]"
                        f"  {model}  in={inp + cached:,}  out={out:,}"
                    )
                else:
                    fd["log"].append(
                        f"[{ts.astimezone().strftime('%H:%M:%S')}] [{tag}]"
                        f"  {model}  req+1"
                    )

            for period, start_utc in starts.items():
                if ts >= start_utc:
                    fd[period]["in"]       += inp
                    fd[period]["out"]      += out
                    fd[period]["cached"]   += cached
                    fd[period]["req"]      += 1
                    fd[period]["chat_req"] += 1 if req_type == "chat" else 0
                    fd[period]["comp_req"] += 1 if req_type == "comp" else 0
                    fd[period]["cost"]     += cost

        return fd
