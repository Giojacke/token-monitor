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

    # Metadato
    detected_at: str = ""

    @property
    def any_installed(self) -> bool:
        return self.claude_installed or self.codex_installed

    @property
    def tools(self) -> list[str]:
        return (["claude"] if self.claude_installed else []) + \
               (["codex"]  if self.codex_installed  else [])

    @property
    def show_claude(self) -> bool:
        return self.claude_installed

    @property
    def show_codex(self) -> bool:
        return self.codex_installed


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

    return d


def detect_or_cached() -> Detection:
    """
    Devuelve la detección cacheada si tiene menos de CACHE_TTL_H horas.
    Si no, corre una detección fresh y la guarda.
    """
    cached = _load_raw()
    if cached:
        try:
            ts   = datetime.fromisoformat(cached.get("detected_at", ""))
            stale = datetime.now() - ts > timedelta(hours=CACHE_TTL_H)
            if not stale:
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

    if not d.any_installed:
        lines.append("  [!!] Ninguna herramienta detectada")

    for l in lines:
        print(l)
