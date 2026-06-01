"""
System Tray para Token Monitor — Windows / macOS / Linux.

Requiere: pip install pystray pillow

Comportamiento:
  - Icono naranja con ◆ en la bandeja del sistema
  - Click izquierdo / doble click → abre la ventana
  - Click derecho → menú contextual
  - Color del icono según % de sesión usado:
      verde  < 50%
      naranja 50-80%
      rojo   > 80%
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

try:
    import pystray
    from PIL import Image

    TRAY_AVAILABLE = True
except ImportError:
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    TRAY_AVAILABLE = False

_ROBOT_PATH = Path(__file__).parent.parent / "image" / "robot_token_monitor.png"


# ── TrayManager ───────────────────────────────────────────────────────────────


class TrayManager:
    """
    Gestiona el icono en la bandeja del sistema.
    En macOS AppKit exige crear el NSStatusItem desde el hilo principal,
    así que usamos pystray.run_detached() antes de entrar al mainloop de Tk.
    En el resto de plataformas se conserva el hilo secundario porque
    pystray.Icon.run() es bloqueante.
    Toda comunicación con Tk va por root.after() — es thread-safe.
    """

    def __init__(
        self,
        root: tk.Tk,
        state,
        runtime_cfg: dict,
        on_open: Callable,
        on_settings: Callable,
        on_quit: Callable,
    ):
        self.root = root
        self.state = state
        self.runtime_cfg = runtime_cfg
        self._on_open = on_open
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._icon: Any | None = None
        self._robot_icon = None  # cargado en start()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not TRAY_AVAILABLE:
            print("[tray] pystray/pillow no instalados — tray desactivado")
            print("[tray]   pip install pystray pillow")
            return
        assert Image is not None
        try:
            self._robot_icon = Image.open(str(_ROBOT_PATH))
        except Exception:
            self._robot_icon = None
        if sys.platform == "darwin":
            # AppKit falla si pystray crea el NSStatusItem desde un thread:
            # "NSWindow should only be instantiated on the main thread".
            # start() se llama desde __main__.py antes de root.mainloop(),
            # por eso acá todavía estamos en el hilo principal.
            self._run_detached()
        else:
            threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        if self._icon:
            with suppress(Exception):
                self._icon.stop()

    # ── actualizar color desde el tick de UI ─────────────────────────────────

    def update_color(self, pct: float) -> None:
        """Actualiza el tooltip con el % actual. Llamar desde cualquier hilo."""
        if not TRAY_AVAILABLE or not self._icon:
            return
        self._icon.title = f"Token Monitor — {int(pct * 100)}%"

    # ── pystray ───────────────────────────────────────────────────────────────

    def _create_icon(self) -> Any:
        assert pystray is not None

        def sess_text(item):
            snap = self.state.snapshot()
            limit = self.runtime_cfg.get("session_limit", 0)
            factor = self.runtime_cfg.get("calibration_factor", 1.0)
            tok = snap.get("cl_5h_out", 0)
            if limit > 0:
                pct = min(tok / limit * factor * 100, 100)
                return f"Claude: {pct:.0f}% sesion"
            return "Claude: calibrar en configuracion"

        def week_text(item):
            from .ui import _sess_reset_text

            txt = _sess_reset_text(self.runtime_cfg)
            return f"Semana: {txt}" if txt else "Semana: configurar reset"

        menu = pystray.Menu(
            pystray.MenuItem("Token Monitor", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir monitor", self._open, default=True),
            pystray.MenuItem("Configuracion", self._settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(sess_text, None, enabled=False),
            pystray.MenuItem(week_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Cerrar", self._quit),
        )

        return pystray.Icon(
            name="token-monitor",
            icon=self._robot_icon,  # pystray redimensiona automáticamente
            title="Token Monitor",
            menu=menu,
        )

    def _run(self) -> None:
        icon = self._create_icon()
        self._icon = icon
        icon.run()

    def _run_detached(self) -> None:
        icon = self._create_icon()
        self._icon = icon
        icon.run_detached()

    # ── callbacks (hilo pystray → Tk via after) ───────────────────────────────

    def _open(self, icon, item) -> None:
        self.root.after(0, self._on_open)

    def _settings(self, icon, item) -> None:
        self.root.after(0, self._on_settings)

    def _quit(self, icon, item) -> None:
        icon.stop()
        self.root.after(0, self._on_quit)
