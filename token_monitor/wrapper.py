"""
Wrapper de Codex CLI — intercepta su stdout para capturar tokens en tiempo real.

Crea tres scripts en ~/.token-monitor/:
  codex-wrapper.sh   → para Git Bash / WSL / macOS / Linux
  codex-wrapper.bat  → para CMD de Windows
  codex-wrapper.ps1  → para PowerShell de Windows

El monitor parsea ~/.token-monitor/codex.log buscando las mismas
líneas JSON que escriben los JSONL de sesión de Codex.
"""

import json
import os
import stat
import threading
import time
from pathlib import Path

from .parser import parse_codex_line
from .state import TokenState, PERIODS

WRAPPER_DIR = Path.home() / ".token-monitor"
CODEX_LOG   = WRAPPER_DIR / "codex.log"

# ── templates de scripts ──────────────────────────────────────────────────────

_SH = """\
#!/bin/bash
# Token Monitor — Codex wrapper (bash)
# Uso: usa este script en vez de 'codex' para capturar tokens en tiempo real
# Ejemplo: alias codex=~/.token-monitor/codex-wrapper.sh
exec codex "$@" 2>&1 | tee -a "{log}"
"""

_BAT = """\
@echo off
REM Token Monitor - Codex wrapper (Windows CMD)
REM Uso: renombra este .bat a codex.bat y ponlo antes de codex en el PATH
REM O simplemente llama: codex-wrapper %*
codex %* 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -Append -FilePath '{log}'"
"""

_PS1 = """\
#!/usr/bin/env pwsh
# Token Monitor - Codex wrapper (PowerShell)
# Uso: Set-Alias codex ~/.token-monitor/codex-wrapper.ps1
& codex @args 2>&1 | Tee-Object -Append -FilePath "{log}"
"""

_INSTRUCTIONS = """\
Token Monitor — Codex Wrapper
==============================

Para capturar tokens de Codex en tiempo real, ejecutá codex a través
de uno de estos wrappers (en vez del binario directo):

  Git Bash / WSL / macOS / Linux:
    ~/.token-monitor/codex-wrapper.sh

    Alias temporal:
      alias codex=~/.token-monitor/codex-wrapper.sh

    Alias permanente en ~/.bashrc:
      alias codex="$HOME/.token-monitor/codex-wrapper.sh"

  PowerShell (Windows):
    ~/.token-monitor/codex-wrapper.ps1

    Alias temporal:
      Set-Alias codex "$env:USERPROFILE\\.token-monitor\\codex-wrapper.ps1"

    Alias permanente en $PROFILE:
      Set-Alias codex "$env:USERPROFILE\\.token-monitor\\codex-wrapper.ps1"

  CMD (Windows):
    ~/.token-monitor/codex-wrapper.bat

Los tokens aparecerán en el monitor dentro de los próximos 5 segundos.
Los logs se guardan en: {log}
"""


# ── creación de scripts ───────────────────────────────────────────────────────

def create_wrapper_scripts() -> dict[str, Path]:
    """Crea los scripts wrapper si no existen. Devuelve rutas creadas."""
    WRAPPER_DIR.mkdir(parents=True, exist_ok=True)
    CODEX_LOG.touch(exist_ok=True)

    log_str = str(CODEX_LOG)
    created: dict[str, Path] = {}

    scripts = [
        ("sh",  WRAPPER_DIR / "codex-wrapper.sh",  _SH),
        ("bat", WRAPPER_DIR / "codex-wrapper.bat", _BAT),
        ("ps1", WRAPPER_DIR / "codex-wrapper.ps1", _PS1),
    ]

    for key, path, template in scripts:
        if not path.exists():
            path.write_text(template.format(log=log_str), encoding="utf-8")
        if key == "sh":
            # chmod +x — funciona en Unix/Mac/WSL, no-op en Windows NTFS
            try:
                path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except Exception:
                pass
        created[key] = path

    inst = WRAPPER_DIR / "INSTRUCCIONES.txt"
    if not inst.exists():
        inst.write_text(_INSTRUCTIONS.format(log=log_str), encoding="utf-8")

    return created


def wrapper_log_has_data() -> bool:
    return CODEX_LOG.exists() and CODEX_LOG.stat().st_size > 0


# ── WrapperScanner — tail del log en tiempo real ──────────────────────────────

class WrapperScanner:
    """
    Hace tail de ~/.token-monitor/codex.log en tiempo real.
    Parsea líneas JSON buscando token_count events (mismo formato que los JSONL
    de sesión de Codex). Actualiza la sesión actual en TokenState.
    """

    def __init__(self, state: TokenState, stop_event: threading.Event):
        self.state  = state
        self._stop  = stop_event
        self._thread = threading.Thread(target=self._run, daemon=True)

        # Acumuladores de sesión (solo lo nuevo desde que arrancó el monitor)
        self._sess = {"in": 0, "out": 0, "cached": 0, "req": 0}
        self._log: list[str] = []

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            f = open(CODEX_LOG, "r", encoding="utf-8", errors="replace")
            f.seek(0, 2)   # arrancar desde el final (solo tokens nuevos)
        except Exception:
            return

        while not self._stop.is_set():
            line = f.readline()
            if line:
                self._process(line)
            else:
                # Detectar rotación / truncado
                try:
                    if CODEX_LOG.stat().st_size < f.tell():
                        f.seek(0)
                except Exception:
                    pass
                time.sleep(0.15)
        f.close()

    def _process(self, line: str) -> None:
        r = parse_codex_line(line)
        if not r:
            return
        ts, inp, out, cached = r

        self._sess["in"]     += inp
        self._sess["out"]    += out
        self._sess["cached"] += cached
        self._sess["req"]    += 1

        from datetime import datetime
        ts_str = ts.astimezone().strftime("%H:%M:%S")
        self._log.append(f"[{ts_str}] [cx-live]  in={inp+cached:,}  out={out:,}")
        if len(self._log) > 40:
            self._log.pop(0)

        # Actualizar solo la sesión (los períodos los maneja CodexScanner)
        curr = self.state.cx
        with self.state.lock:
            for k in ("in", "out", "cached", "req"):
                self.state.cx["sess"][k] = self._sess[k]
            self.state.cx_log = self._log[-40:]
