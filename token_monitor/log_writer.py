"""
DailyLogger — escribe dos archivos en ~/.token-monitor/logs/

1. YYYY-MM-DD.csv
   Resumen diario, una fila por proveedor+modelo.
   Se sobreescribe cada 60 s con los totales actualizados.
   Columnas: provider, model, date, tokens_in, tokens_out, requests, cost_usd

2. YYYY-MM-DD-activity.txt
   Cada entrada del activity log tal como aparece en la UI, en tiempo real.
   Modo append — nunca se sobreescribe, crece durante el día.
   Se actualiza cada 10 s.
   Ejemplo:
     [21:25:49] [cx]  gpt-5.4  in=73,244  out=195
     [21:26:40] [gm]  gemini-3-flash-preview  in=30,106  out=502
     [21:26:58] [ch]  gpt-4o  req+1
"""

import csv
import re
import threading
import time
from collections import defaultdict
from datetime import date

from .config import LOGS_DIR
from .parser import calc_cost, calc_gemini_cost, calc_codex_cost, calc_copilot_cost


# ── parseo de entradas del activity log ───────────────────────────────────────
#   [HH:MM:SS] [tag]  model  in=N  out=N
#   [HH:MM:SS] [tag]  model  req+1
_RE_TOK = re.compile(
    r"\[\d{2}:\d{2}:\d{2}\] \[(\w+)\]\s+(\S+)\s+in=([\d,]+)\s+out=([\d,]+)"
)
_RE_REQ = re.compile(
    r"\[\d{2}:\d{2}:\d{2}\] \[(\w+)\]\s+(\S+)\s+req\+1"
)

_TAG_PROVIDER = {
    "cl": "claude",
    "cx": "codex",
    "gm": "gemini",
    "ch": "copilot",
    "cp": "copilot",
}


def _cost_for(provider: str, model: str, in_tok: int, out_tok: int) -> float:
    if provider == "claude":
        return calc_cost(in_tok, out_tok, 0, 0, model)
    if provider == "codex":
        return calc_codex_cost(in_tok, out_tok, 0, model)
    if provider == "gemini":
        return calc_gemini_cost(in_tok, out_tok, 0, model)
    if provider == "copilot":
        return calc_copilot_cost(in_tok, out_tok, 0, model)
    return 0.0


class DailyLogger:
    def __init__(self, state, stop_event: threading.Event):
        self.state  = state
        self._stop  = stop_event
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()   # entradas ya escritas en activity.txt
        self._today: str     = ""
        self._tick: int      = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                today = date.today().isoformat()
                if today != self._today:
                    self._seen  = set()
                    self._today = today
                    self._tick  = 0

                self._append_activity(today)

                self._tick += 1
                if self._tick % 6 == 0:   # cada 60 s
                    self._write_summary(today)
            except Exception:
                pass
            time.sleep(10)

    # ── activity log (append en tiempo real) ──────────────────────────────────

    def _append_activity(self, today: str) -> None:
        all_entries = self.state.full_activity()
        new = [e for e in all_entries if e not in self._seen]
        if not new:
            return
        act_file = LOGS_DIR / f"{today}-activity.txt"
        with open(act_file, "a", encoding="utf-8") as f:
            for entry in new:
                f.write(entry + "\n")
        self._seen.update(new)

    # ── resumen diario CSV (por proveedor+modelo) ─────────────────────────────

    def _write_summary(self, today: str) -> None:
        model_totals: dict[tuple, dict] = defaultdict(
            lambda: {"in": 0, "out": 0, "req": 0, "cost": 0.0}
        )

        for entry in self._seen:
            m = _RE_TOK.search(entry)
            if m:
                tag, model = m.group(1), m.group(2)
                in_tok     = int(m.group(3).replace(",", ""))
                out_tok    = int(m.group(4).replace(",", ""))
                provider   = _TAG_PROVIDER.get(tag, tag)
                key        = (provider, model)
                model_totals[key]["in"]   += in_tok
                model_totals[key]["out"]  += out_tok
                model_totals[key]["req"]  += 1
                model_totals[key]["cost"] += _cost_for(provider, model, in_tok, out_tok)
                continue

            m2 = _RE_REQ.search(entry)
            if m2:
                tag, model = m2.group(1), m2.group(2)
                provider   = _TAG_PROVIDER.get(tag, tag)
                key        = (provider, model)
                model_totals[key]["req"] += 1

        if not model_totals:
            return

        log_file = LOGS_DIR / f"{today}.csv"
        with open(log_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "provider", "model", "date",
                "tokens_in", "tokens_out", "requests", "cost_usd",
            ])
            for (provider, model), d in sorted(model_totals.items()):
                writer.writerow([
                    provider, model, today,
                    d["in"], d["out"], d["req"],
                    f"{d['cost']:.6f}",
                ])
