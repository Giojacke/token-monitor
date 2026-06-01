"""
Ventana de configuración — se abre con ⚙ en el header.

Sección 1 — Calibrar desde la web:
  Ingresás los % que muestra claude.ai/settings/limits
  → el monitor back-calcula los límites reales de tu plan
  → de ahí en adelante trackea acumulando sobre esa base

Sección 2 — Ajustes generales:
  Límite semanal, presupuesto diario

Mismos colores y fuentes que el monitor principal.
"""

import json
import tkinter as tk
from tkinter import font as tkfont

from .config import (
    BG, BG2, BG3, BORDER,
    CLAUDE_C, SESS_BAR, WEEK_BAR, DIM, TEXT, WHITE,
    CLAUDE_PRO_WEEKLY_LIMIT,
)
from .detector import CONFIG_PATH


class SettingsWindow:
    W = 340
    H = 540

    def __init__(self, parent: tk.Tk, runtime_cfg: dict, state, on_save):
        """
        parent      — ventana principal
        runtime_cfg — dict mutable con weekly_limit, session_limit, daily_budget
        state       — TokenState para leer tokens actuales en la calibración
        on_save     — callback(runtime_cfg) al guardar
        """
        self._parent     = parent
        self.runtime_cfg = runtime_cfg
        self.state       = state
        self.on_save     = on_save

        self.win = tk.Toplevel(parent)
        self.win.overrideredirect(True)
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)

        px, py = parent.winfo_x(), parent.winfo_y()
        self.win.geometry(f"{self.W}x{self.H}+{max(0, px - self.W - 8)}+{py}")

        self._dragging = False
        self._dx = self._dy = 0

        f_sm = tkfont.Font(family="Courier New", size=8)
        f_md = tkfont.Font(family="Courier New", size=9)
        f_hd = tkfont.Font(family="Courier New", size=9, weight="bold")

        self._build(f_sm, f_md, f_hd)
        self._bind_drag()

    # ── construcción ─────────────────────────────────────────────────────────

    def _build(self, f_sm, f_md, f_hd) -> None:
        # Header
        hdr = tk.Frame(self.win, bg="#111", height=28)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="CONFIGURACION", bg="#111", fg=CLAUDE_C,
                 font=f_hd).pack(side="left", padx=10)
        tk.Button(hdr, text="X", bg="#111", fg=DIM, bd=0, padx=6,
                  font=f_sm, activebackground="#111", activeforeground="white",
                  command=self.win.destroy).pack(side="right")

        body = tk.Frame(self.win, bg=BG, padx=14, pady=10)
        body.pack(fill="both", expand=True)

        # ── Sección 1: Calibrar desde la web ──────────────────────────────────
        tk.Label(body, text="CALIBRAR DESDE claude.ai/settings/limits",
                 bg=BG, fg=CLAUDE_C, font=f_hd).pack(anchor="w")
        tk.Label(body,
                 text="Ingresa los valores actuales que muestra la web.\n"
                      "El monitor calcula los limites reales de tu plan.",
                 bg=BG, fg=DIM, font=f_sm, justify="left").pack(anchor="w", pady=(2, 6))

        cal = tk.Frame(body, bg=BG)
        cal.pack(fill="x")
        cal.columnconfigure(1, weight=1)

        # Sesión actual %
        tk.Label(cal, text="Sesion actual  (%)", bg=BG, fg=SESS_BAR,
                 font=f_sm, width=22, anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        self.var_sess_pct = tk.StringVar(value="84")
        self._entry(cal, self.var_sess_pct, f_md, SESS_BAR).grid(row=0, column=1, sticky="ew", padx=(8,0))

        # Sesión reset en (minutos)
        tk.Label(cal, text="Reset sesion en (min)", bg=BG, fg=DIM,
                 font=f_sm, width=22, anchor="w").grid(row=1, column=0, sticky="w", pady=2)
        self.var_sess_reset_min = tk.StringVar(value="74")
        self._entry(cal, self.var_sess_reset_min, f_md, DIM).grid(row=1, column=1, sticky="ew", padx=(8,0))

        # Semanal %
        tk.Label(cal, text="Semanal        (%)", bg=BG, fg=WEEK_BAR,
                 font=f_sm, width=22, anchor="w").grid(row=2, column=0, sticky="w", pady=2)
        self.var_week_pct = tk.StringVar(value="12")
        self._entry(cal, self.var_week_pct, f_md, WEEK_BAR).grid(row=2, column=1, sticky="ew", padx=(8,0))

        # Reset semanal (texto libre)
        tk.Label(cal, text="Reset semanal (ej. mar 15:00)", bg=BG, fg=DIM,
                 font=f_sm, width=22, anchor="w").grid(row=3, column=0, sticky="w", pady=2)
        saved_reset = self.runtime_cfg.get("weekly_reset_str", "mar 15:00")
        self.var_week_reset = tk.StringVar(value=saved_reset)
        self._entry(cal, self.var_week_reset, f_md, DIM).grid(row=3, column=1, sticky="ew", padx=(8,0))

        tk.Button(body, text="Calibrar limites", bg=SESS_BAR, fg="#000", bd=0,
                  font=f_md, padx=8, pady=3,
                  activebackground="#c07800", activeforeground="#000",
                  command=self._calibrate).pack(fill="x", pady=(10, 2))

        # ── Sección 1b: Recalibrar factor ─────────────────────────────────────
        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(8, 4))
        tk.Label(body, text="RECALIBRAR FACTOR",
                 bg=BG, fg=DIM, font=f_hd).pack(anchor="w")
        tk.Label(body,
                 text="Abre claude.ai/settings y dime los % actuales.\n"
                      "Ajusta el factor sin recalcular los limites.",
                 bg=BG, fg=DIM, font=f_sm, justify="left").pack(anchor="w", pady=(2, 4))

        rec = tk.Frame(body, bg=BG)
        rec.pack(fill="x")
        rec.columnconfigure(1, weight=1)

        tk.Label(rec, text="Sesion actual  (%)", bg=BG, fg=SESS_BAR,
                 font=f_sm, width=22, anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        self.var_recal_sess = tk.StringVar(value="")
        self._entry(rec, self.var_recal_sess, f_md, SESS_BAR).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        tk.Label(rec, text="Semanal        (%)", bg=BG, fg=WEEK_BAR,
                 font=f_sm, width=22, anchor="w").grid(row=1, column=0, sticky="w", pady=2)
        self.var_recal_week = tk.StringVar(value="")
        self._entry(rec, self.var_recal_week, f_md, WEEK_BAR).grid(row=1, column=1, sticky="ew", padx=(8, 0))

        tk.Button(body, text="Recalibrar factor", bg="#3b5bdb", fg="white", bd=0,
                  font=f_md, padx=8, pady=3,
                  activebackground="#2d4cc7", activeforeground="white",
                  command=self._recalibrate_factor).pack(fill="x", pady=(8, 0))

        # Separador
        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=10)

        # ── Sección 2: Ajustes generales ──────────────────────────────────────
        tk.Label(body, text="AJUSTES GENERALES", bg=BG, fg=DIM,
                 font=f_hd).pack(anchor="w")

        gen = tk.Frame(body, bg=BG)
        gen.pack(fill="x", pady=(6, 0))
        gen.columnconfigure(1, weight=1)

        tk.Label(gen, text="Limite semanal (M tok)", bg=BG, fg=DIM,
                 font=f_sm, width=22, anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        wl_m = round(self.runtime_cfg.get("weekly_limit", CLAUDE_PRO_WEEKLY_LIMIT) / 1_000_000, 2)
        self.var_weekly_m = tk.StringVar(value=str(wl_m))
        self._entry(gen, self.var_weekly_m, f_md, WHITE).grid(row=0, column=1, sticky="ew", padx=(8,0))

        tk.Label(gen, text="Presupuesto diario (USD)", bg=BG, fg=DIM,
                 font=f_sm, width=22, anchor="w").grid(row=1, column=0, sticky="w", pady=2)
        self.var_budget = tk.StringVar(value=str(round(self.runtime_cfg.get("daily_budget", 10.0), 2)))
        self._entry(gen, self.var_budget, f_md, WHITE).grid(row=1, column=1, sticky="ew", padx=(8,0))

        tk.Button(body, text="Guardar", bg=BG3, fg=TEXT, bd=0,
                  font=f_md, padx=8, pady=3,
                  activebackground=BG2, activeforeground=WHITE,
                  command=self._save_general).pack(fill="x", pady=(10, 2))

        # Status
        self.lbl_status = tk.Label(body, text="", bg=BG, fg=DIM, font=f_sm)
        self.lbl_status.pack(anchor="w", pady=(4, 0))

    def _entry(self, parent, var, font, hl_color) -> tk.Entry:
        return tk.Entry(parent, textvariable=var, bg=BG3, fg=WHITE, font=font,
                        insertbackground=WHITE, bd=0, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=hl_color)

    # ── calibración ───────────────────────────────────────────────────────────

    def _calibrate(self) -> None:
        """
        Lee los tokens actuales del scanner y back-calcula los límites:
          session_limit = tokens_5h / (session_pct / 100)
          weekly_limit  = tokens_week / (weekly_pct / 100)
        """
        try:
            sess_pct  = float(self.var_sess_pct.get()) / 100
            week_pct  = float(self.var_week_pct.get()) / 100
            reset_min = int(self.var_sess_reset_min.get())
        except ValueError:
            self.lbl_status.config(text="Error: valores invalidos", fg="#e07348")
            return

        if sess_pct <= 0 or week_pct <= 0:
            self.lbl_status.config(text="Los % deben ser > 0", fg="#e07348")
            return

        snap = self.state.snapshot()
        tok_5h   = snap.get("cl_5h_out", 0)
        tok_week = snap.get("cl_week_out", 0)

        if tok_5h == 0:
            self.lbl_status.config(
                text="Sin output tokens en las ultimas 5h.\n"
                     "Usa Claude Code un momento y reintenta.", fg="#e07348")
            return
        if tok_week == 0:
            self.lbl_status.config(
                text="Sin output tokens esta semana.\n"
                     "Espera 5s y reintenta.", fg="#e07348")
            return

        session_limit = int(tok_5h   / sess_pct)
        weekly_limit  = int(tok_week / week_pct)

        from datetime import datetime
        self.runtime_cfg["session_limit"]      = session_limit
        self.runtime_cfg["weekly_limit"]       = weekly_limit
        self.runtime_cfg["weekly_reset_str"]   = self.var_week_reset.get().strip()
        self.runtime_cfg["sess_reset_min"]     = reset_min
        self.runtime_cfg["calibration_time"]   = datetime.now().isoformat()
        self.runtime_cfg["calibration_tok_5h"] = tok_5h
        self.runtime_cfg["calibration_factor"] = 1.0   # reset al recalibrar límites

        self._persist()
        self.on_save(self.runtime_cfg)

        # Actualizar campo de límite semanal con el valor calculado
        self.var_weekly_m.set(str(round(weekly_limit / 1_000_000, 2)))

        msg = (f"Calibrado:\n"
               f"  sesion limit  = {session_limit:,} tok\n"
               f"  semanal limit = {weekly_limit:,} tok")
        self.lbl_status.config(text=msg, fg=SESS_BAR)

    # ── guardar general ───────────────────────────────────────────────────────

    def _recalibrate_factor(self) -> None:
        """
        Calcula el factor de corrección comparando % de la web con output_tokens del monitor.
        No cambia session_limit ni weekly_limit — solo ajusta el multiplicador.
        """
        try:
            web_sess_pct = float(self.var_recal_sess.get()) / 100
            web_week_pct = float(self.var_recal_week.get()) / 100
        except ValueError:
            self.lbl_status.config(text="Error: valores invalidos", fg="#e07348")
            return

        if web_sess_pct <= 0 or web_week_pct <= 0:
            self.lbl_status.config(text="Los % deben ser > 0", fg="#e07348")
            return

        session_limit = self.runtime_cfg.get("session_limit", 0)
        weekly_limit  = self.runtime_cfg.get("weekly_limit",  0)

        if session_limit == 0:
            self.lbl_status.config(
                text="Calibra los limites primero (boton arriba).", fg="#e07348")
            return

        snap     = self.state.snapshot()
        tok_sess = snap.get("cl_5h_out",  0)
        tok_week = snap.get("cl_week_out", 0)

        if tok_sess == 0:
            self.lbl_status.config(
                text="Sin output tokens de sesion.\nUsa Claude Code y reintenta.", fg="#e07348")
            return

        monitor_sess_raw = tok_sess / session_limit
        factor_sess      = web_sess_pct / monitor_sess_raw

        if tok_week > 0 and weekly_limit > 0:
            monitor_week_raw = tok_week / weekly_limit
            factor_week      = web_week_pct / monitor_week_raw
            factor           = round((factor_sess + factor_week) / 2, 4)
        else:
            factor = round(factor_sess, 4)

        self.runtime_cfg["calibration_factor"] = factor
        self._persist()
        self.on_save(self.runtime_cfg)

        resultado_pct = min(monitor_sess_raw * factor, 1.0) * 100
        self.lbl_status.config(
            text=f"Factor: x{factor:.3f}  "
                 f"({monitor_sess_raw*100:.1f}% -> {resultado_pct:.1f}%)",
            fg=SESS_BAR)

    def _save_general(self) -> None:
        try:
            weekly_m = float(self.var_weekly_m.get().replace(",", "."))
            budget   = float(self.var_budget.get().replace(",", "."))
        except ValueError:
            self.lbl_status.config(text="Error: valores invalidos", fg="#e07348")
            return

        self.runtime_cfg["weekly_limit"]  = int(weekly_m * 1_000_000)
        self.runtime_cfg["daily_budget"]  = budget
        self.runtime_cfg["weekly_reset_str"] = self.var_week_reset.get().strip()
        self._persist()
        self.on_save(self.runtime_cfg)
        self.lbl_status.config(text="Guardado", fg=CLAUDE_C)
        self.win.after(1200, self.win.destroy)

    # ── persistencia ─────────────────────────────────────────────────────────

    def _persist(self) -> None:
        try:
            raw = {}
            if CONFIG_PATH.exists():
                raw = json.loads(CONFIG_PATH.read_text())
            raw.update({
                "claude_weekly_limit":  self.runtime_cfg.get("weekly_limit"),
                "claude_session_limit": self.runtime_cfg.get("session_limit"),
                "daily_budget":         self.runtime_cfg.get("daily_budget"),
                "weekly_reset_str":     self.runtime_cfg.get("weekly_reset_str", ""),
                "sess_reset_min":       self.runtime_cfg.get("sess_reset_min", 0),
                "calibration_time":     self.runtime_cfg.get("calibration_time", ""),
                "calibration_factor":   self.runtime_cfg.get("calibration_factor", 1.0),
            })
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False))
        except Exception as e:
            self.lbl_status.config(text=f"Error guardando: {e}", fg="#e07348")

    # ── drag ─────────────────────────────────────────────────────────────────

    def _bind_drag(self) -> None:
        self.win.bind("<ButtonPress-1>",   self._on_press)
        self.win.bind("<B1-Motion>",       self._on_drag)
        self.win.bind("<ButtonRelease-1>", lambda e: setattr(self, "_dragging", False))

    def _on_press(self, e) -> None:
        self._dx = e.x_root - self.win.winfo_x()
        self._dy = e.y_root - self.win.winfo_y()
        self._dragging = True

    def _on_drag(self, e) -> None:
        if self._dragging:
            self.win.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")
