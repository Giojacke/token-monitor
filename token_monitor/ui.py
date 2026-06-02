import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime, timedelta

from .config import (
    BG, BG2, BG3, BORDER,
    CLAUDE_C, SESS_BAR, WEEK_BAR, CODEX_C, GEMINI_C, COPILOT_C, DIM, TEXT, WHITE,
    REFRESH_MS, LOG_LINES,
    WINDOW_W, WINDOW_H_EXPANDED, WINDOW_H_COLLAPSED,
    CLAUDE_PRO_WEEKLY_LIMIT, CLAUDE_SESSION_WINDOW_H, COPILOT_PLANES,
)
from .state import TokenState
from .settings_ui import SettingsWindow
from .i18n import t


# ── formateo de números ───────────────────────────────────────────────────────

def fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_cost(c: float) -> str:
    if c >= 100:
        return f"${c:.0f}"
    if c >= 10:
        return f"${c:.1f}"
    return f"${c:.2f}"


def make_bar(canvas: tk.Canvas, w: int, h: int, pct: float, color: str) -> None:
    canvas.delete("all")
    canvas.create_rectangle(0, 0, w, h, fill=BG3, outline=BORDER, width=1)
    fill_w = max(0, min(int(w * pct), w - 2))
    if fill_w > 2:
        canvas.create_rectangle(1, 1, 1 + fill_w, h - 1, fill=color, outline="")


# ── constantes de columnas ────────────────────────────────────────────────────

# (key_i18n, period_key) — el label se traduce con t(key_i18n) en build/apply_language
COL_PERIODS  = [("today", "today"), ("week", "week"), ("month", "month"), ("year", "year")]
COL_W        = 7


def _weekly_reset_str() -> str:
    """Tiempo hasta el próximo lunes a medianoche (reset aproximado del límite semanal)."""
    now  = datetime.now()
    days = (7 - now.weekday()) % 7 or 7          # días hasta el próximo lunes
    nxt  = (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    rem  = nxt - now
    h    = int(rem.total_seconds() // 3600)
    m    = int((rem.total_seconds() % 3600) // 60)
    return f"reset en {h}h {m}m"


def _sess_reset_text(runtime_cfg: dict) -> str:
    """
    Tiempo real hasta el próximo reset de la ventana de sesión de 5h.
    Maneja múltiples ciclos: si la ventana ya reseteó, calcula el próximo.
    """
    cal_str   = runtime_cfg.get("calibration_time", "")
    reset_min = runtime_cfg.get("sess_reset_min", 0)
    if not cal_str or not reset_min:
        return ""
    try:
        from .config import CLAUDE_SESSION_WINDOW_H
        cal_time    = datetime.fromisoformat(cal_str)
        first_reset = cal_time + timedelta(minutes=reset_min)
        now         = datetime.now()
        if now < first_reset:
            remaining_sec = (first_reset - now).total_seconds()
        else:
            window_sec    = CLAUDE_SESSION_WINDOW_H * 3600
            elapsed_sec   = (now - first_reset).total_seconds()
            remaining_sec = window_sec - (elapsed_sec % window_sec)
        h = int(remaining_sec // 3600)
        m = int((remaining_sec % 3600) // 60)
        return f"reset en {h}h {m}min" if h > 0 else f"reset en {m}min"
    except Exception:
        return ""


class TokenMonitorApp:
    """Ventana flotante con minimize/maximize y tabla de 4 períodos por provider."""

    def __init__(self, root: tk.Tk, state: TokenState,
                 daily_budget: float, detection=None, codex_poller=None,
                 runtime_cfg: dict | None = None, demo: bool = False):
        self.root          = root
        self.state         = state
        self.detection     = detection
        self.codex_poller  = codex_poller
        self.demo          = demo
        self._collapsed    = False
        self._dragging     = False
        self._drag_x = self._drag_y = 0
        self._settings_win  = None
        self.tray_manager   = None
        self._translatable: list = []   # (widget, i18n_key) para _apply_language()

        # Config mutable — compartida con SettingsWindow
        self.runtime_cfg = runtime_cfg or {
            "weekly_limit": CLAUDE_PRO_WEEKLY_LIMIT,
            "daily_budget": daily_budget,
        }

        # Qué bloques mostrar (default False para Gemini/Copilot si no hay detección)
        self._show_cl = (detection.show_claude   if detection else True)
        self._show_cx = (detection.show_codex    if detection else True)
        self._show_gm = (detection.show_gemini   if detection else False)
        self._show_cp = (detection.show_copilot  if detection else False)

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        root.configure(bg=BG)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{WINDOW_W}x{WINDOW_H_EXPANDED}+"
                      f"{sw - WINDOW_W - 24}+{sh - WINDOW_H_EXPANDED - 60}")

        self.f_mono_sm = tkfont.Font(family="Courier New", size=8)
        self.f_mono_md = tkfont.Font(family="Courier New", size=10)
        self.f_title   = tkfont.Font(family="Courier New", size=9,  weight="bold")
        self.f_hdr     = tkfont.Font(family="Courier New", size=13, weight="bold")

        self._build_ui()
        self._apply_language()
        self._bind_drag()
        self._tick()

    # ── construcción ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_header()

        # ── Canvas scrollable + scrollbar autohide ────────────────────────────
        self._scroll_outer = tk.Frame(self.root, bg=BG)
        self._scroll_outer.pack(fill="both", expand=True)
        self._scroll_outer.grid_rowconfigure(0, weight=1)
        self._scroll_outer.grid_columnconfigure(0, weight=1)

        self._scroll_canvas = tk.Canvas(
            self._scroll_outer, bg=BG, bd=0, highlightthickness=0,
            yscrollcommand=self._on_scroll_update,
        )
        self._scroll_canvas.grid(row=0, column=0, sticky="nsew")

        self._scrollbar = tk.Scrollbar(
            self._scroll_outer, orient="vertical", width=8,
            bg="#333333", troughcolor="#1c1c1c",
            activebackground="#555555", relief="flat",
            command=self._scroll_canvas.yview,
        )
        # columna 1 reservada; se activa en _on_scroll_update cuando hay overflow
        self._scroll_outer.grid_columnconfigure(1, weight=0, minsize=0)

        self._body = tk.Frame(self._scroll_canvas, bg=BG, padx=12, pady=8)
        self._canvas_win = self._scroll_canvas.create_window(
            (0, 0), window=self._body, anchor="nw")

        self._scroll_canvas.bind("<Configure>",      self._on_canvas_configure)
        self._body.bind("<Configure>",               self._on_inner_configure)
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # ── Contenido ─────────────────────────────────────────────────────────
        if not (self._show_cl or self._show_cx or self._show_gm or self._show_cp):
            self._build_no_tools_msg(self._body)
        else:
            # Frames por proveedor — se muestran/ocultan con _apply_visibility()
            if self._show_cl:
                self._claude_frame = tk.Frame(self._body, bg=BG)
                self._build_claude_bars(self._claude_frame)

            self._sep_cl_cx = tk.Frame(self._body, bg=BORDER, height=1)

            if self._show_cx:
                self._codex_frame = tk.Frame(self._body, bg=BG)
                self._add_provider_block(self._codex_frame, "CODEX CLI", CODEX_C, "cx")

            self._sep_cx_gm = tk.Frame(self._body, bg=BORDER, height=1)

            if self._show_gm:
                self._gm_frame = tk.Frame(self._body, bg=BG)
                self._add_provider_block(self._gm_frame, "GEMINI CLI", GEMINI_C, "gm")

            self._sep_gm_cp = tk.Frame(self._body, bg=BORDER, height=1)

            if self._show_cp:
                self._cp_frame = tk.Frame(self._body, bg=BG)
                self._add_provider_block(self._cp_frame, "COPILOT", COPILOT_C, "cp")
                # Nota extra: aporte individual en plan empresarial
                self.lbl_cp_enterprise_note = tk.Label(
                    self._cp_frame, text="", bg=BG, fg=DIM,
                    font=self.f_mono_sm, justify="left")
                self.lbl_cp_enterprise_note.pack(anchor="w", pady=(0, 2))

            # Stats y log siempre visibles — anclan el orden de pack con before=
            self._sep_stats = tk.Frame(self._body, bg=BORDER, height=1)
            self._sep_stats.pack(fill="x", pady=5)
            self._build_stats(self._body)
            tk.Frame(self._body, bg=BORDER, height=1).pack(fill="x", pady=5)
            self._build_log(self._body)

            # Aplica visibilidad inicial según preferencias guardadas
            self._apply_visibility()

        # ── Footer fijo (fuera del scroll) ────────────────────────────────────
        self._footer = tk.Frame(self.root, bg="#0a0a0a", height=22)
        self._footer.pack(fill="x")
        self._footer.pack_propagate(False)
        self.lbl_status = tk.Label(self._footer, text=t("scanning"),
                                   bg="#0a0a0a", fg=DIM, font=self.f_mono_sm)
        self.lbl_status.pack(side="left", padx=10)
        self._btn_reset = tk.Button(
            self._footer, text=t("reset"), bg="#0a0a0a", fg=DIM, bd=0,
            font=self.f_mono_sm, activebackground="#0a0a0a", activeforeground=TEXT,
            command=lambda: self.state.reset())
        self._btn_reset.pack(side="right", padx=10)
        self._translatable.append((self._btn_reset, "reset"))

    def _build_header(self) -> None:
        hdr = tk.Frame(self.root, bg="#111", height=WINDOW_H_COLLAPSED)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Robot 24×24 — NEAREST preserva el pixel art
        try:
            from PIL import Image as _Img, ImageTk as _ITk
            from pathlib import Path as _Path
            _raw = _Img.open(_Path(__file__).parent.parent / "image" / "robot_token_monitor.png")
            self._robot_img = _ITk.PhotoImage(_raw.resize((24, 24), _Img.NEAREST))
            tk.Label(hdr, image=self._robot_img, bg="#111").pack(side="left", padx=(10, 0))
        except Exception:
            self._robot_img = None
        tk.Label(hdr, text="TOKEN MONITOR", bg="#111", fg="#34d399",
                 font=self.f_hdr).pack(side="left", padx=(4, 0))
        if self.demo:
            tk.Label(hdr, text="DEMO", bg="#1a1200", fg="#febc2e",
                     font=self.f_mono_sm, padx=4).pack(side="left")

        # Botones de ventana (derecha → izquierda): ✕  —  ⚙  ● LIVE
        tk.Button(hdr, text="✕", bg="#111", fg=DIM, bd=0, padx=6,
                  font=self.f_mono_sm, activebackground="#111",
                  activeforeground="white",
                  command=self._on_close).pack(side="right")

        self._btn_toggle = tk.Button(
            hdr, text="—", bg="#111", fg=DIM, bd=0, padx=6,
            font=self.f_mono_sm, activebackground="#111",
            activeforeground=TEXT, command=self._toggle_collapse,
        )
        self._btn_toggle.pack(side="right")

        tk.Button(hdr, text="⚙", bg="#111", fg=DIM, bd=0, padx=6,
                  font=self.f_mono_sm, activebackground="#111",
                  activeforeground=CLAUDE_C,
                  command=self._open_settings).pack(side="right")

        tk.Label(hdr, text="● LIVE", bg="#111", fg="#28c840",
                 font=self.f_mono_sm).pack(side="right", padx=4)

    def _build_weekly_bar(self) -> None:
        """Barra de uso semanal Claude Pro — siempre visible, colapsa con el body."""
        self._weekly_frame = tk.Frame(self.root, bg="#0f0f0f", padx=10, pady=4)
        self._weekly_frame.pack(fill="x")

        top = tk.Frame(self._weekly_frame, bg="#0f0f0f")
        top.pack(fill="x")
        tk.Label(top, text="CLAUDE semanal", bg="#0f0f0f", fg=CLAUDE_C,
                 font=self.f_mono_sm).pack(side="left")
        self.lbl_week_pct   = tk.Label(top, text="0%", bg="#0f0f0f",
                                        fg=WHITE, font=self.f_mono_sm)
        self.lbl_week_reset = tk.Label(top, text="", bg="#0f0f0f",
                                        fg=DIM,  font=self.f_mono_sm)
        self.lbl_week_reset.pack(side="right")
        self.lbl_week_pct.pack(side="right", padx=6)

        self.cv_weekly = tk.Canvas(self._weekly_frame, bg="#0f0f0f",
                                   height=10, bd=0, highlightthickness=0)
        self.cv_weekly.pack(fill="x", pady=(3, 0))

    # ── Claude bars (sesión + semanal como la web) ────────────────────────────

    def _build_claude_bars(self, parent: tk.Frame) -> None:
        """
        Replica las dos barras de claude.ai/settings/limits:
          Sesión actual  ████████░░░  84%   reset en 1h 14m
          Semanal        ██░░░░░░░░░  12%   reset mar 15:00
        """
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=2)

        self.lbl_claude_title = tk.Label(f, text="◆ CLAUDE CODE  — Plan Pro",
                                          bg=BG, fg=CLAUDE_C, font=self.f_title)
        self.lbl_claude_title.pack(anchor="w")

        # ── Sesión actual (ventana de 5h) ─────────────────────────────────────
        sess_f = tk.Frame(f, bg=BG)
        sess_f.pack(fill="x", pady=(6, 0))

        top_s = tk.Frame(sess_f, bg=BG)
        top_s.pack(fill="x")
        lbl_s = tk.Label(top_s, text=t("session"), bg=BG, fg=TEXT, font=self.f_mono_sm)
        lbl_s.pack(side="left")
        self._translatable.append((lbl_s, "session"))
        self.lbl_sess_pct   = tk.Label(top_s, text="0%", bg=BG, fg=WHITE,
                                        font=self.f_mono_sm)
        self.lbl_sess_reset = tk.Label(top_s, text="", bg=BG, fg=DIM,
                                        font=self.f_mono_sm)
        self.lbl_sess_reset.pack(side="right")
        self.lbl_sess_pct.pack(side="right", padx=6)

        self.cv_sess = tk.Canvas(sess_f, bg=BG, height=10, bd=0, highlightthickness=0)
        self.cv_sess.pack(fill="x", pady=(3, 0))

        # sub-row: costo equiv | hint calibrar
        sub_s = tk.Frame(sess_f, bg=BG)
        sub_s.pack(fill="x")
        self.lbl_sess_cost = tk.Label(sub_s, text="equiv. API: $0.00",
                                       bg=BG, fg=DIM, font=self.f_mono_sm)
        self.lbl_sess_cost.pack(side="left")
        self.lbl_sess_hint = tk.Label(sub_s, text="calibrar en ⚙",
                                       bg=BG, fg=SESS_BAR, font=self.f_mono_sm)
        self.lbl_sess_hint.pack(side="right")

        # ── Semanal ────────────────────────────────────────────────────────────
        week_f = tk.Frame(f, bg=BG)
        week_f.pack(fill="x", pady=(8, 0))

        top_w = tk.Frame(week_f, bg=BG)
        top_w.pack(fill="x")
        lbl_w = tk.Label(top_w, text=t("weekly"), bg=BG, fg=TEXT, font=self.f_mono_sm)
        lbl_w.pack(side="left")
        self._translatable.append((lbl_w, "weekly"))
        self.lbl_cl_week_pct   = tk.Label(top_w, text="0%", bg=BG, fg=WHITE,
                                           font=self.f_mono_sm)
        self.lbl_cl_week_reset = tk.Label(top_w, text="", bg=BG, fg=DIM,
                                           font=self.f_mono_sm)
        self.lbl_cl_week_reset.pack(side="right")
        self.lbl_cl_week_pct.pack(side="right", padx=6)

        self.cv_cl_week = tk.Canvas(week_f, bg=BG, height=10, bd=0, highlightthickness=0)
        self.cv_cl_week.pack(fill="x", pady=(3, 0))

        self.lbl_cl_week_cost = tk.Label(week_f, text="equiv. API: $0.00",
                                          bg=BG, fg=DIM, font=self.f_mono_sm)
        self.lbl_cl_week_cost.pack(anchor="w")

        # ── Tabla de períodos HOY / SEM / MES / AÑO ───────────────────────────
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(10, 5))

        tbl = tk.Frame(f, bg=BG)
        tbl.pack(fill="x")

        col0 = tk.Frame(tbl, bg=BG)
        col0.pack(side="left")
        for txt in ("", "tok", "$"):
            tk.Label(col0, text=txt, bg=BG, fg=DIM,
                     font=self.f_mono_sm, width=4, anchor="w").pack()

        for key, period in COL_PERIODS:
            col = tk.Frame(tbl, bg=BG)
            col.pack(side="left", expand=True, fill="x")
            hdr = tk.Label(col, text=t(key), bg=BG, fg=DIM,
                           font=self.f_mono_sm, width=COL_W, anchor="e")
            hdr.pack()
            self._translatable.append((hdr, key))
            lbl_tok  = tk.Label(col, text="0",  bg=BG, fg=CLAUDE_C,
                                font=self.f_mono_sm, width=COL_W, anchor="e")
            lbl_cost = tk.Label(col, text="$0", bg=BG, fg=DIM,
                                font=self.f_mono_sm, width=COL_W, anchor="e")
            lbl_tok.pack()
            lbl_cost.pack()
            setattr(self, f"lbl_cl_tbl_{period}_tok",  lbl_tok)
            setattr(self, f"lbl_cl_tbl_{period}_cost", lbl_cost)

    # ── provider block (Codex) ────────────────────────────────────────────────

    def _add_provider_block(self, parent: tk.Frame, name: str,
                            color: str, key: str) -> None:
        root_f = tk.Frame(parent, bg=BG)
        root_f.pack(fill="x", pady=2)

        # Título (referencia guardada para actualizarlo con el modelo)
        title_row = tk.Frame(root_f, bg=BG)
        title_row.pack(fill="x")
        lbl_title = tk.Label(title_row, text=f"◆ {name}", bg=BG, fg=color,
                             font=self.f_title)
        lbl_title.pack(side="left")
        setattr(self, f"lbl_{key}_title", lbl_title)

        # Barra de progreso (costo hoy vs presupuesto)
        cv = tk.Canvas(root_f, bg=BG, height=8, bd=0, highlightthickness=0)
        cv.pack(fill="x", pady=(2, 3))

        # Tabla de períodos
        table = tk.Frame(root_f, bg=BG)
        table.pack(fill="x")

        # Columna etiqueta (vacía + "tok" + "$")
        col0 = tk.Frame(table, bg=BG)
        col0.pack(side="left")
        tk.Label(col0, text="",    bg=BG, fg=DIM, font=self.f_mono_sm,
                 width=4, anchor="w").pack()
        tk.Label(col0, text="tok", bg=BG, fg=DIM, font=self.f_mono_sm,
                 width=4, anchor="w").pack()
        tk.Label(col0, text="$",   bg=BG, fg=DIM, font=self.f_mono_sm,
                 width=4, anchor="w").pack()

        # Columnas de períodos (col_key = i18n key, period = snapshot key)
        for col_key, period in COL_PERIODS:
            col = tk.Frame(table, bg=BG)
            col.pack(side="left", expand=True, fill="x")
            hdr = tk.Label(col, text=t(col_key), bg=BG, fg=DIM,
                           font=self.f_mono_sm, width=COL_W, anchor="e")
            hdr.pack()
            self._translatable.append((hdr, col_key))

            lbl_tok  = tk.Label(col, text="0", bg=BG, fg=color,
                                font=self.f_mono_sm, width=COL_W, anchor="e")
            lbl_cost = tk.Label(col, text="$0", bg=BG, fg=DIM,
                                font=self.f_mono_sm, width=COL_W, anchor="e")
            lbl_tok.pack()
            lbl_cost.pack()

            setattr(self, f"lbl_{key}_{period}_tok",  lbl_tok)
            setattr(self, f"lbl_{key}_{period}_cost", lbl_cost)

        setattr(self, f"cv_{key}", cv)

    # ── stats y log ──────────────────────────────────────────────────────────

    def _build_stats(self, parent: tk.Frame) -> None:
        sf = tk.Frame(parent, bg=BG)
        sf.pack(fill="x", pady=2)
        self.lbl_total_cost = self._stat_card(sf, "total_today", "$0.00", WHITE)
        self.lbl_week_cost  = self._stat_card(sf, "total_week",  "$0.00", TEXT)
        self.lbl_month_cost = self._stat_card(sf, "total_month", "$0.00", TEXT)
        self.lbl_year_cost  = self._stat_card(sf, "total_year",  "$0.00", DIM)

    def _build_no_tools_msg(self, parent: tk.Frame) -> None:
        f = tk.Frame(parent, bg=BG)
        f.pack(expand=True, pady=40)
        tk.Label(f, text="no se detectó claude code ni codex cli",
                 bg=BG, fg=DIM, font=self.f_mono_sm).pack()
        tk.Label(f, text="instala alguno y reinicia el monitor",
                 bg=BG, fg=DIM, font=self.f_mono_sm).pack(pady=(4, 0))

    def _build_log(self, parent: tk.Frame) -> None:
        lbl = tk.Label(parent, text=t("activity_log"), bg=BG, fg=DIM, font=self.f_mono_sm)
        lbl.pack(anchor="w")
        self._translatable.append((lbl, "activity_log"))
        lf = tk.Frame(parent, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
        lf.pack(fill="both", expand=True, pady=(2, 2))
        self.log_text = tk.Text(
            lf, bg=BG2, fg="#666", font=self.f_mono_sm, bd=0,
            state="disabled", wrap="none", height=LOG_LINES,
            insertbackground=BG2, selectbackground=BG2,
        )
        self.log_text.pack(fill="both", expand=True, padx=6, pady=3)

    def _stat_card(self, parent: tk.Frame, label: str,
                   init: str, color: str) -> tk.Label:
        f = tk.Frame(parent, bg=BG3, highlightthickness=1, highlightbackground=BORDER)
        f.pack(side="left", expand=True, fill="x", padx=2)
        tk.Label(f, text=label, bg=BG3, fg=DIM, font=self.f_mono_sm).pack(pady=(3, 0))
        lbl = tk.Label(f, text=init, bg=BG3, fg=color, font=self.f_mono_md)
        lbl.pack(pady=(0, 3))
        return lbl

    # ── tray integration ─────────────────────────────────────────────────────

    def set_tray_manager(self, tray) -> None:
        self.tray_manager = tray

    def show(self) -> None:
        """Restaura la ventana desde la tray."""
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()

    def hide(self) -> None:
        """Oculta la ventana a la tray."""
        self.root.withdraw()

    def _on_close(self) -> None:
        """X del header: oculta a tray si close_to_tray, sino cierra."""
        if self.runtime_cfg.get("close_to_tray", True) and self.tray_manager:
            self.hide()
        else:
            self._quit()

    def _quit(self) -> None:
        """Cierre real del programa."""
        if self.tray_manager:
            self.tray_manager.stop()
        self.root.destroy()

    # ── visibilidad de proveedores ────────────────────────────────────────────

    def _apply_visibility(self) -> None:
        """Muestra u oculta bloques de proveedor según runtime_cfg."""
        if not hasattr(self, "_sep_stats"):
            return
        show_cl = self._show_cl and self.runtime_cfg.get("show_claude",  True)
        show_cx = self._show_cx and self.runtime_cfg.get("show_codex",   True)
        show_gm = self._show_gm and self.runtime_cfg.get("show_gemini",  True)
        show_cp = self._show_cp and self.runtime_cfg.get("show_copilot", True)

        # Reset: quita todos del layout
        for attr in ("_claude_frame", "_sep_cl_cx", "_codex_frame",
                     "_sep_cx_gm", "_gm_frame", "_sep_gm_cp", "_cp_frame"):
            if hasattr(self, attr):
                getattr(self, attr).pack_forget()

        # Re-pack en orden correcto justo antes del separador de stats
        if show_cl and hasattr(self, "_claude_frame"):
            self._claude_frame.pack(fill="x", pady=2, before=self._sep_stats)

        if show_cl and (show_cx or show_gm or show_cp) and hasattr(self, "_sep_cl_cx"):
            self._sep_cl_cx.pack(fill="x", pady=5, before=self._sep_stats)

        if show_cx and hasattr(self, "_codex_frame"):
            self._codex_frame.pack(fill="x", pady=2, before=self._sep_stats)

        if show_cx and (show_gm or show_cp) and hasattr(self, "_sep_cx_gm"):
            self._sep_cx_gm.pack(fill="x", pady=5, before=self._sep_stats)

        if show_gm and hasattr(self, "_gm_frame"):
            self._gm_frame.pack(fill="x", pady=2, before=self._sep_stats)

        if show_gm and show_cp and hasattr(self, "_sep_gm_cp"):
            self._sep_gm_cp.pack(fill="x", pady=5, before=self._sep_stats)

        if show_cp and hasattr(self, "_cp_frame"):
            self._cp_frame.pack(fill="x", pady=2, before=self._sep_stats)

    # ── scroll helpers ────────────────────────────────────────────────────────

    def _on_inner_configure(self, event) -> None:
        self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._scroll_canvas.itemconfig(self._canvas_win, width=event.width)

    def _on_scroll_update(self, first: str, last: str) -> None:
        """Autohide: scrollbar visible solo cuando el contenido no cabe."""
        self._scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            if self._scrollbar.winfo_ismapped():
                self._scrollbar.grid_remove()
        else:
            if not self._scrollbar.winfo_ismapped():
                self._scrollbar.grid(row=0, column=1, sticky="ns")

    def _on_mousewheel(self, event) -> None:
        self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── minimize / maximize ───────────────────────────────────────────────────

    def _toggle_collapse(self) -> None:
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if self._collapsed:
            self._scroll_outer.pack(fill="both", expand=True)
            self._footer.pack(fill="x")
            self.root.geometry(f"{WINDOW_W}x{WINDOW_H_EXPANDED}+{x}+{y}")
            self._btn_toggle.config(text="—")
            self._collapsed = False
        else:
            self._scroll_outer.pack_forget()
            self._footer.pack_forget()
            self.root.geometry(f"{WINDOW_W}x{WINDOW_H_COLLAPSED}+{x}+{y}")
            self._btn_toggle.config(text="□")
            self._collapsed = True

    # ── drag ─────────────────────────────────────────────────────────────────

    def _bind_drag(self) -> None:
        self.root.bind("<ButtonPress-1>",   self._on_press)
        self.root.bind("<B1-Motion>",       self._on_drag)
        self.root.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, e) -> None:
        self._drag_x = e.x_root - self.root.winfo_x()
        self._drag_y = e.y_root - self.root.winfo_y()
        self._dragging = True

    def _on_drag(self, e) -> None:
        if self._dragging:
            self.root.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    def _on_release(self, e) -> None:
        self._dragging = False

    # ── settings ─────────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        if self._settings_win and self._settings_win.win.winfo_exists():
            self._settings_win.win.lift()
            return
        self._settings_win = SettingsWindow(
            self.root,
            self.runtime_cfg,
            state=self.state,
            on_save=self._apply_settings,
        )

    def _apply_language(self) -> None:
        """Actualiza todos los widgets registrados en _translatable al idioma activo."""
        for widget, key in self._translatable:
            try:
                widget.config(text=t(key))
            except Exception:
                pass
        if hasattr(self, "lbl_status"):
            self.lbl_status.config(text=t("scanning"))

    def _apply_settings(self, cfg: dict) -> None:
        """Callback cuando SettingsWindow guarda — aplica de inmediato."""
        self.runtime_cfg = cfg
        self._apply_visibility()
        self._apply_language()

    # ── tick de actualización ─────────────────────────────────────────────────

    def _tick(self) -> None:
        if not self._collapsed:
            snap          = self.state.snapshot()
            budget        = self.runtime_cfg.get("daily_budget", 10.0)
            weekly_limit  = self.runtime_cfg.get("weekly_limit",  CLAUDE_PRO_WEEKLY_LIMIT)
            session_limit = self.runtime_cfg.get("session_limit", 0)   # 0 = sin calibrar
            factor        = self.runtime_cfg.get("calibration_factor", 1.0)

            # ── Claude: título con modelo detectado ───────────────────────────
            if self._show_cl and hasattr(self, "lbl_claude_title"):
                model = snap.get("cl_last_model", "")
                short = model.replace("claude-", "") if model and model != "default" else ""
                pp    = t("plan_pro")
                title = f"◆ CLAUDE CODE  — {short}  [{pp}]" if short else f"◆ CLAUDE CODE  — [{pp}]"
                self.lbl_claude_title.config(text=title)

            # ── Claude: barra de sesión (5h) ──────────────────────────────────
            if self._show_cl and hasattr(self, "cv_sess"):
                tok_5h   = snap.get("cl_5h_out", 0)
                cost_5h  = snap.get("cl_5h_cost", 0)
                sess_pct = min(tok_5h / session_limit * factor, 1.0) if session_limit > 0 else 0

                w = self.cv_sess.winfo_width() or (WINDOW_W - 24)
                make_bar(self.cv_sess, w, 10, sess_pct, SESS_BAR)
                self.lbl_sess_pct.config(text=f"{sess_pct*100:.1f}%")
                self.lbl_sess_cost.config(text=f"{t('equiv_api')} {fmt_cost(cost_5h)}")

                # Reset timer — countdown real con manejo de múltiples ciclos
                reset_txt = _sess_reset_text(self.runtime_cfg)
                self.lbl_sess_reset.config(text=reset_txt)

                # Hint de calibración — desaparece cuando ya está calibrado
                if session_limit == 0:
                    self.lbl_sess_hint.config(text=t("calibrate_hint"))
                else:
                    self.lbl_sess_hint.config(text="")

                # Actualiza color del icono en tray
                if self.tray_manager:
                    self.tray_manager.update_color(sess_pct)

            # ── Claude: barra semanal ─────────────────────────────────────────
            if self._show_cl and hasattr(self, "cv_cl_week"):
                tok_week  = snap.get("cl_week_out", 0)
                cost_week = snap.get("cl_week_cost", 0)
                week_pct  = min(tok_week / max(weekly_limit, 1) * factor, 1.0)

                w = self.cv_cl_week.winfo_width() or (WINDOW_W - 24)
                make_bar(self.cv_cl_week, w, 10, week_pct, WEEK_BAR)
                self.lbl_cl_week_pct.config(text=f"{week_pct*100:.1f}%")
                self.lbl_cl_week_cost.config(text=f"{t('equiv_api')} {fmt_cost(cost_week)}")

                # Reset semanal — usa el string guardado en config o el calculado
                week_reset = self.runtime_cfg.get("weekly_reset_str", "")
                if not week_reset:
                    week_reset = _weekly_reset_str()
                    week_reset = week_reset.replace("reset en ", "")  # "Xh Ym"
                    week_reset = f"en {week_reset}"
                self.lbl_cl_week_reset.config(text=f"{t('resets_on')} {week_reset}")

            # ── Claude: tabla HOY / SEM / MES / AÑO ─────────────────────────
            if self._show_cl:
                for _, period in COL_PERIODS:
                    tok  = snap.get(f"cl_{period}_tok", 0)
                    cost = snap.get(f"cl_{period}_cost", 0)
                    if hasattr(self, f"lbl_cl_tbl_{period}_tok"):
                        getattr(self, f"lbl_cl_tbl_{period}_tok").config(text=fmt_tok(tok))
                        getattr(self, f"lbl_cl_tbl_{period}_cost").config(text=fmt_cost(cost))

            # ── Codex: título con modelo detectado ────────────────────────────
            if self._show_cx and hasattr(self, "lbl_cx_title"):
                cx_model = snap.get("cx_last_model", "")
                cx_short = cx_model if cx_model else t("unknown")
                self.lbl_cx_title.config(
                    text=f"◆ CODEX CLI  — {cx_short}  [{t('chatgpt_plus')}]")

            # ── Codex provider block ──────────────────────────────────────────
            if self._show_cx and hasattr(self, "cv_cx"):
                today_cost = snap.get("cx_today_cost", 0)
                pct = min(today_cost / budget, 1.0) if budget > 0 else 0
                w   = self.cv_cx.winfo_width() or (WINDOW_W - 24)
                make_bar(self.cv_cx, w, 8, pct, CODEX_C)
                for _, period in COL_PERIODS:
                    tok  = snap.get(f"cx_{period}_tok", 0)
                    cost = snap.get(f"cx_{period}_cost", 0)
                    if hasattr(self, f"lbl_cx_{period}_tok"):
                        getattr(self, f"lbl_cx_{period}_tok").config(text=fmt_tok(tok))
                        getattr(self, f"lbl_cx_{period}_cost").config(text=fmt_cost(cost))

            # ── Gemini: título con modelo detectado ───────────────────────────
            if self._show_gm and hasattr(self, "lbl_gm_title"):
                gm_model = snap.get("gm_last_model", "")
                gm_short  = gm_model if gm_model else t("unknown")
                self.lbl_gm_title.config(
                    text=f"◆ GEMINI CLI  — {gm_short}  [{t('google_ai')}]")

            # ── Gemini provider block — barra de actividad logarítmica ───────
            # 0 tok → 0%  |  100K → 25%  |  500K → 100%  (log10 scale)
            if self._show_gm and hasattr(self, "cv_gm"):
                import math
                tok_gm_sess = snap.get("gm_sess_tok", 0)
                pct = min(math.log10(1 + tok_gm_sess / 100_000) / math.log10(6), 1.0)
                w   = self.cv_gm.winfo_width() or (WINDOW_W - 24)
                make_bar(self.cv_gm, w, 8, pct, GEMINI_C)
                for _, period in COL_PERIODS:
                    tok  = snap.get(f"gm_{period}_tok", 0)
                    cost = snap.get(f"gm_{period}_cost", 0)
                    if hasattr(self, f"lbl_gm_{period}_tok"):
                        getattr(self, f"lbl_gm_{period}_tok").config(text=fmt_tok(tok))
                        getattr(self, f"lbl_gm_{period}_cost").config(text=fmt_cost(cost))

            # ── Copilot: título + barra según plan ───────────────────────────
            if self._show_cp and hasattr(self, "lbl_cp_title"):
                cp_plan  = self.runtime_cfg.get("copilot_plan", "unknown")
                cp_model = snap.get("cp_last_model", "")
                cp_short = cp_model if cp_model else t("unknown")
                plan_info = COPILOT_PLANES.get(cp_plan, {})
                plan_label = plan_info.get("label", t("github_enterprise"))
                self.lbl_cp_title.config(
                    text=f"◆ COPILOT  — {cp_short}  [{plan_label}]")

            if self._show_cp and hasattr(self, "cv_cp"):
                cp_plan      = self.runtime_cfg.get("copilot_plan", "unknown")
                month_cost   = snap.get("cp_month_cost", 0)
                month_req    = snap.get("cp_month_req",  0)

                if cp_plan == "free":
                    # barra: completions este mes / 2000 (límite mensual del plan free)
                    free_limit = COPILOT_PLANES["free"].get("completions_mes", 2000)
                    pct = min(month_req / free_limit, 1.0) if free_limit > 0 else 0
                else:
                    # pro / pro+ / business / enterprise: req vs referencia configurable
                    req_ref = self.runtime_cfg.get("copilot_req_ref", 500)
                    pct = min(month_req / req_ref, 1.0) if req_ref > 0 else 0

                w = self.cv_cp.winfo_width() or (WINDOW_W - 24)
                make_bar(self.cv_cp, w, 8, pct, COPILOT_C)

                for _, period in COL_PERIODS:
                    tok  = snap.get(f"cp_{period}_tok", 0)
                    cost = snap.get(f"cp_{period}_cost", 0)
                    if hasattr(self, f"lbl_cp_{period}_tok"):
                        getattr(self, f"lbl_cp_{period}_tok").config(text=fmt_tok(tok))
                        getattr(self, f"lbl_cp_{period}_cost").config(text=fmt_cost(cost))

                # nota empresarial
                if hasattr(self, "lbl_cp_enterprise_note"):
                    if cp_plan in ("business", "enterprise"):
                        self.lbl_cp_enterprise_note.config(text=t("copilot_enterprise_note"))
                    else:
                        self.lbl_cp_enterprise_note.config(text="")

            # ── stats totales ─────────────────────────────────────────────────
            if hasattr(self, "lbl_total_cost"):
                self.lbl_total_cost.config(text=fmt_cost(snap.get("total_today_cost", 0)))
                self.lbl_week_cost.config(text=fmt_cost(snap.get("total_week_cost", 0)))
                self.lbl_month_cost.config(text=fmt_cost(snap.get("total_month_cost", 0)))
                self.lbl_year_cost.config(text=fmt_cost(snap.get("total_year_cost", 0)))

            # ── log ──────────────────────────────────────────────────────────
            if hasattr(self, "log_text"):
                self.log_text.config(state="normal")
                self.log_text.delete("1.0", "end")
                for line in snap["log"][-LOG_LINES:]:
                    if "[cx]" in line:
                        tag = "cx"
                    elif "[gm]" in line:
                        tag = "gm"
                    elif "[cp]" in line:
                        tag = "cp"
                    else:
                        tag = "cl"
                    self.log_text.insert("end", line + "\n", tag)
                self.log_text.tag_config("cl", foreground=CLAUDE_C)
                self.log_text.tag_config("cx", foreground=CODEX_C)
                self.log_text.tag_config("gm", foreground=GEMINI_C)
                self.log_text.tag_config("cp", foreground=COPILOT_C)
                self.log_text.config(state="disabled")

        self.root.after(REFRESH_MS, self._tick)

    def set_status(self, msg: str) -> None:
        self.lbl_status.config(text=msg)
