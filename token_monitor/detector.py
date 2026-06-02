"""
Detección de herramientas instaladas al arrancar el monitor.

Corre antes de crear cualquier ventana. Detecta:
  - Claude Code (binario + logs en ~/.claude/projects/)
  - Codex CLI   (binario + logs en ~/.codex/sessions/)

Persiste el resultado en ~/.config/token-monitor/config.json
para que reinicios posteriores arranquen sin preguntar nada.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

from .config import PROJECTS_DIR, CODEX_SESSIONS_DIR
from .gemini_scanner import find_gemini_chats_dir
from .copilot_scanner import find_copilot_dirs, find_copilot_log_files

CONFIG_PATH = Path.home() / ".config" / "token-monitor" / "config.json"
CACHE_TTL_H = 24   # horas antes de repetir la detección


# ── resultado de detección ────────────────────────────────────────────────────

@dataclass
class Detection:
    # Claude
    claude_installed: bool  = False
    claude_bin:       str   = ""
    claude_has_logs:  bool  = False
    claude_log_path:  str   = ""

    # Codex
    codex_installed:  bool  = False
    codex_bin:        str   = ""
    codex_has_logs:   bool  = False

    # Gemini
    gemini_installed: bool  = False
    gemini_bin:       str   = ""
    gemini_has_logs:  bool  = False

    # GitHub Copilot (extensión VS Code — sin binario propio)
    copilot_installed: bool = False
    copilot_has_logs:  bool = False
    copilot_log_path:  str  = ""

    # Metadato
    detected_at: str = ""

    @property
    def any_installed(self) -> bool:
        return (self.claude_installed or self.codex_installed
                or self.gemini_installed or self.copilot_installed)

    @property
    def tools(self) -> list[str]:
        return (["claude"]  if self.claude_installed  else []) + \
               (["codex"]   if self.codex_installed   else []) + \
               (["gemini"]  if self.gemini_installed  else []) + \
               (["copilot"] if self.copilot_installed else [])

    @property
    def show_claude(self) -> bool:
        return self.claude_installed

    @property
    def show_codex(self) -> bool:
        return self.codex_installed

    @property
    def show_gemini(self) -> bool:
        return self.gemini_installed

    @property
    def show_copilot(self) -> bool:
        return self.copilot_installed


# ── detección ─────────────────────────────────────────────────────────────────

def detect() -> Detection:
    """Detecta qué herramientas están instaladas. Siempre corre fresh."""
    d = Detection(detected_at=datetime.now().isoformat())

    # ── Claude Code ──
    d.claude_bin       = shutil.which("claude") or ""
    d.claude_installed = bool(d.claude_bin)

    if PROJECTS_DIR.exists():
        main = [f for f in PROJECTS_DIR.rglob("*.jsonl") if "subagents" not in f.parts]
        if main:
            d.claude_has_logs  = True
            d.claude_log_path  = str(max(main, key=lambda f: f.stat().st_mtime))

    # ── Codex CLI ──
    d.codex_bin       = shutil.which("codex") or ""
    d.codex_installed = bool(d.codex_bin)

    if CODEX_SESSIONS_DIR.exists():
        found = next(CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"), None)
        d.codex_has_logs = found is not None

    # ── Gemini CLI ──
    d.gemini_bin       = shutil.which("gemini") or ""
    d.gemini_installed = bool(d.gemini_bin)

    chats_dir = find_gemini_chats_dir()
    if chats_dir is not None:
        d.gemini_has_logs = next(chats_dir.glob("session-*.jsonl"), None) is not None

    # ── GitHub Copilot ──
    copilot_dirs = find_copilot_dirs()
    d.copilot_installed = bool(copilot_dirs)
    if copilot_dirs:
        d.copilot_log_path = str(copilot_dirs[0])
        log_files = find_copilot_log_files(copilot_dirs)
        d.copilot_has_logs = bool(log_files)

    return d


def detect_or_cached() -> Detection:
    """
    Devuelve la detección cacheada si:
      - tiene menos de CACHE_TTL_H horas, Y
      - contiene todos los campos del dataclass Detection (sin campos faltantes).
    Si falta algún campo (p.ej. al agregar soporte para un proveedor nuevo),
    trata la caché como stale y re-detecta automáticamente.
    """
    cached = _load_raw()
    if cached:
        try:
            ts    = datetime.fromisoformat(cached.get("detected_at", ""))
            stale = datetime.now() - ts > timedelta(hours=CACHE_TTL_H)
            missing = any(
                f not in cached
                for f in Detection.__dataclass_fields__
                if f != "detected_at"
            )
            if not stale and not missing:
                return Detection(**{k: cached[k] for k in Detection.__dataclass_fields__ if k in cached})
        except Exception:
            pass

    fresh = detect()
    save_config(fresh)
    return fresh


# ── persistencia ──────────────────────────────────────────────────────────────

def save_config(detection: Detection, extra: dict | None = None) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(detection)
    data["detected_tools"] = detection.tools
    if extra:
        data.update(extra)
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _load_raw() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


# ── diagnóstico por consola ───────────────────────────────────────────────────

def print_detection(d: Detection) -> None:
    lines = ["[token-monitor] Detección de herramientas:"]

    if d.claude_installed:
        lines.append(f"  [OK] Claude Code  -> {d.claude_bin}")
        if d.claude_has_logs:
            lines.append(f"       logs: {d.claude_log_path}")
        else:
            lines.append("       logs: ninguno encontrado (esperando sesion)")
    else:
        lines.append("  [--] Claude Code  -> no instalado")

    if d.codex_installed:
        lines.append(f"  [OK] Codex CLI    -> {d.codex_bin}")
        if d.codex_has_logs:
            lines.append("       logs: ~/.codex/sessions/")
        else:
            lines.append("       logs: ninguno encontrado")
    else:
        lines.append("  [--] Codex CLI    -> no instalado")

    if d.gemini_installed:
        lines.append(f"  [OK] Gemini CLI   -> {d.gemini_bin}")
        if d.gemini_has_logs:
            lines.append("       logs: ~/.gemini/tmp/")
        else:
            lines.append("       logs: ninguno encontrado")
    else:
        lines.append("  [--] Gemini CLI   -> no instalado")

    if d.copilot_installed:
        lines.append(f"  [OK] GitHub Copilot -> {d.copilot_log_path}")
        if d.copilot_has_logs:
            lines.append("       logs: encontrados")
        else:
            lines.append("       logs: ninguno encontrado")
    else:
        lines.append("  [--] GitHub Copilot -> no detectado")

    if not d.any_installed:
        lines.append("  [!!] Ninguna herramienta detectada")

    for l in lines:
        print(l)
