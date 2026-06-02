"""
DailyLogger — escribe un resumen diario de tokens en ~/.token-monitor/logs/

Un archivo por día: YYYY-MM-DD.txt
Formato CSV separado por comas, una fila por proveedor con totales del día.
Se actualiza cada 60 segundos (overwrite del día actual).

Ejemplo de salida (2026-06-02.txt):
  provider,model,date,tokens_in,tokens_out,tokens_cached,requests,cost_usd
  claude,sonnet-4-6,2026-06-02,284231,3667,272564,15,0.055005
  gemini,gemini-3-flash-preview,2026-06-02,55944,502,22626,9,0.000433
"""

import csv
import threading
import time
from datetime import date

from .config import LOGS_DIR


class DailyLogger:
    """
    Lee el snapshot del TokenState cada 60s y sobreescribe el archivo del día
    con los totales actualizados de cada proveedor.
    """

    def __init__(self, state, stop_event: threading.Event):
        self.state = state
        self._stop = stop_event
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._write()
            except Exception:
                pass
            time.sleep(60)

    def _write(self) -> None:
        snap      = self.state.snapshot()
        today_str = date.today().isoformat()
        log_file  = LOGS_DIR / f"{today_str}.txt"

        rows: list[list] = []

        # ── Claude ─────────────────────────────────────────────────────────────
        cl_req  = snap.get("cl_today_req",  0)
        if cl_req > 0:
            cl_in   = snap.get("cl_today_in",   0)
            cl_out  = snap.get("cl_today_out",  0)
            cl_cw   = snap.get("cl_today_input_tok", 0) - cl_in   # cache_w + cache_r
            cl_cost = snap.get("cl_today_cost", 0.0)
            cl_mod  = snap.get("cl_last_model", "unknown").replace("claude-", "")
            rows.append([
                "claude", cl_mod, today_str,
                cl_in, cl_out, cl_cw, cl_req,
                f"{cl_cost:.6f}",
            ])

        # ── Codex ──────────────────────────────────────────────────────────────
        cx_req  = snap.get("cx_today_req",  0)
        if cx_req > 0:
            cx_in     = snap.get("cx_today_in",     0)
            cx_out    = snap.get("cx_today_out",    0)
            cx_cached = snap.get("cx_today_cached", 0)
            cx_cost   = snap.get("cx_today_cost",   0.0)
            cx_mod    = snap.get("cx_last_model",   "unknown")
            rows.append([
                "codex", cx_mod, today_str,
                cx_in, cx_out, cx_cached, cx_req,
                f"{cx_cost:.6f}",
            ])

        # ── Gemini ─────────────────────────────────────────────────────────────
        gm_req  = snap.get("gm_today_req",  0)
        if gm_req > 0:
            gm_in     = snap.get("gm_today_in",     0)
            gm_out    = snap.get("gm_today_out",    0)
            gm_cached = snap.get("gm_today_cached", 0)
            gm_cost   = snap.get("gm_today_cost",   0.0)
            gm_mod    = snap.get("gm_last_model",   "unknown")
            rows.append([
                "gemini", gm_mod, today_str,
                gm_in, gm_out, gm_cached, gm_req,
                f"{gm_cost:.6f}",
            ])

        # ── Copilot ────────────────────────────────────────────────────────────
        cp_req  = snap.get("cp_today_req",  0)
        if cp_req > 0:
            cp_in     = snap.get("cp_today_in",     0)
            cp_out    = snap.get("cp_today_out",    0)
            cp_cached = snap.get("cp_today_cached", 0)
            cp_cost   = snap.get("cp_today_cost",   0.0)
            cp_mod    = snap.get("cp_last_model",   "unknown")
            rows.append([
                "copilot", cp_mod, today_str,
                cp_in, cp_out, cp_cached, cp_req,
                f"{cp_cost:.6f}",
            ])

        if not rows:
            return

        with open(log_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "provider", "model", "date",
                "tokens_in", "tokens_out", "tokens_cached",
                "requests", "cost_usd",
            ])
            writer.writerows(rows)
