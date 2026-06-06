"""
ChartWindow — ventana de gráficas de consumo de tokens.

4 mini-gráficas de barras (HOY / SEM / MES / AÑO), una por proveedor visible.
Se auto-refresca cada 2 segundos leyendo el snapshot del estado.

Copilot: sus logs no exponen tokens, así que la barra queda en 0 pero se
muestra el conteo de requests debajo (ej. "25r") para que no parezca vacío.
"""

import tkinter as tk
from tkinter import font as tkfont

from .config import (
    BG, BG2, BG3, BORDER, TEXT, DIM, WHITE,
    CLAUDE_C, CODEX_C, GEMINI_C, COPILOT_C,
)


# ── datos de cada proveedor ───────────────────────────────────────────────────

_PROVIDERS = [
    # (prefix, abbr,  nombre completo,    color,      tok_tpl,        req_tpl)
    ("cl", "CL", "◆ CLAUDE CODE",  CLAUDE_C,  "cl_{p}_tok",   "cl_{p}_req"),
    ("cx", "CX", "◆ CODEX CLI",    CODEX_C,   "cx_{p}_tok",   "cx_{p}_req"),
    ("gm", "GM", "◆ GEMINI CLI",   GEMINI_C,  "gm_{p}_tok",   "gm_{p}_req"),
    ("cp", "CP", "◆ COPILOT",      COPILOT_C, "cp_{p}_tok",   "cp_{p}_chat_req"),
]

_PERIODS = [
    ("today", "HOY"),
    ("week",  "SEM"),
    ("month", "MES"),
    ("year",  "AÑO"),
]

CHART_W  = 195
CHART_H  = 130
REFRESH  = 2000   # ms


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


class ChartWindow:
    """
    Se instancia desde TokenMonitorApp._open_chart().
    get_visible: callable → dict {"cl": bool, "cx": bool, "gm": bool, "cp": bool}
    """

    def __init__(self, parent_root, state, get_visible):
        self._win = tk.Toplevel(parent_root)
        self._win.configure(bg=BG)
        self._win.resizable(False, False)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)

        self.state        = state
        self.get_visible  = get_visible
        self._canvases: dict[str, tk.Canvas] = {}
        self._legend_frm: tk.Frame | None = None

        self._f_sm  = tkfont.Font(family="Courier New", size=7)
        self._f_md  = tkfont.Font(family="Courier New", size=9, weight="bold")
        self._f_hdr = tkfont.Font(family="Courier New", size=9, weight="bold")
        self._f_leg = tkfont.Font(family="Courier New", size=8, weight="bold")

        self._build()
        self._position(parent_root)
        self._refresh()

    # ── construcción ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(self._win, bg="#111", height=26)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="TOKEN USAGE", bg="#111", fg=TEXT,
                 font=self._f_hdr).pack(side="left", padx=10)
        tk.Button(hdr, text="✕", bg="#111", fg=DIM, bd=0, padx=6,
                  font=self._f_sm, activebackground="#111",
                  activeforeground=WHITE,
                  command=self._win.destroy).pack(side="right")

        # ── Leyenda (se reconstruye en cada refresh) ──────────────────────
        self._legend_frm = tk.Frame(self._win, bg=BG2, pady=5)
        self._legend_frm.pack(fill="x", padx=8, pady=(6, 0))

        # ── Separador ────────────────────────────────────────────────────────
        tk.Frame(self._win, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(4, 0))

        # ── 2×2 grid de mini-gráficas ────────────────────────────────────────
        body = tk.Frame(self._win, bg=BG, padx=8, pady=8)
        body.pack(fill="both", expand=True)

        for i, (period_key, period_label) in enumerate(_PERIODS):
            row, col = divmod(i, 2)

            cell = tk.Frame(body, bg=BG2,
                            highlightbackground=BORDER, highlightthickness=1)
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

            tk.Label(cell, text=period_label, bg=BG2, fg=TEXT,
                     font=self._f_md, pady=3).pack()

            cv = tk.Canvas(cell, bg=BG2, width=CHART_W, height=CHART_H,
                           bd=0, highlightthickness=0)
            cv.pack(padx=6, pady=(0, 6))
            self._canvases[period_key] = cv

        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

    # ── leyenda ───────────────────────────────────────────────────────────────

    def _rebuild_legend(self, active: list) -> None:
        for w in self._legend_frm.winfo_children():
            w.destroy()

        for pfx, abbr, nombre, col, *_ in active:
            tk.Label(
                self._legend_frm,
                text=nombre,
                bg=BG2, fg=col,
                font=self._f_leg,
                padx=8,
            ).pack(side="left")

    # ── refresco de datos ─────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if not self._win.winfo_exists():
            return

        snap    = self.state.snapshot()
        visible = self.get_visible()

        active = [p for p in _PROVIDERS if visible.get(p[0], False)]

        self._rebuild_legend(active)

        for period_key, _ in _PERIODS:
            self._draw_chart(self._canvases[period_key],
                             period_key, snap, active)

        self._win.after(REFRESH, self._refresh)

    # ── dibujo de una mini-gráfica ────────────────────────────────────────────

    def _draw_chart(self, cv: tk.Canvas, period: str,
                    snap: dict, active: list) -> None:
        cv.delete("all")

        if not active:
            cv.create_text(CHART_W // 2, CHART_H // 2,
                           text="sin datos", fill=DIM, font=self._f_sm)
            return

        n          = len(active)
        pad_l      = 10
        pad_r      = 10
        pad_top    = 18
        pad_bot    = 18
        bar_area_w = CHART_W - pad_l - pad_r
        bar_area_h = CHART_H - pad_top - pad_bot

        slot_w = bar_area_w // n
        bar_w  = max(int(slot_w * 0.55), 6)

        values: list[tuple] = []
        for pfx, abbr, nombre, col, tok_tpl, req_tpl in active:
            tok = snap.get(tok_tpl.format(p=period), 0)
            req = snap.get(req_tpl.format(p=period), 0)
            values.append((abbr, col, tok, req, pfx == "cp"))

        max_tok = max((v[2] for v in values), default=0) or 1

        for j, (abbr, col, tok, req, is_cp) in enumerate(values):
            x_center = pad_l + j * slot_w + slot_w // 2
            bar_h    = int((tok / max_tok) * bar_area_h) if tok else 0
            bar_h    = min(bar_h, bar_area_h)

            x0     = x_center - bar_w // 2
            x1     = x_center + bar_w // 2
            y_base = pad_top + bar_area_h
            y_top  = y_base - bar_h

            # Barra
            if bar_h > 0:
                cv.create_rectangle(x0, y_top, x1, y_base,
                                    fill=col, outline="", width=0)
            else:
                cv.create_rectangle(x0, y_base - 2, x1, y_base,
                                    fill=BG3, outline="", width=0)

            # Valor encima
            if is_cp:
                val_text = f"{req}r" if req else "0r"
                val_col  = col if req else DIM
            else:
                val_text = _fmt(tok) if tok else "0"
                val_col  = col if tok else DIM

            cv.create_text(x_center, y_top - 3,
                           text=val_text, fill=val_col,
                           font=self._f_sm, anchor="s")

            # Abreviatura del proveedor debajo (sin colisión: CL/CX/GM/CP)
            cv.create_text(x_center, y_base + 3,
                           text=abbr, fill=col,
                           font=self._f_sm, anchor="n")

    # ── posición ──────────────────────────────────────────────────────────────

    def _position(self, parent_root) -> None:
        self._win.update_idletasks()
        px = parent_root.winfo_x()
        py = parent_root.winfo_y()
        ww = self._win.winfo_width()
        self._win.geometry(f"+{px - ww - 8}+{py}")

    def is_alive(self) -> bool:
        try:
            return self._win.winfo_exists()
        except Exception:
            return False

    def lift(self) -> None:
        self._win.lift()
