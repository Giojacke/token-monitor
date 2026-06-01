import threading
from datetime import datetime


PERIODS = ("sess", "5h", "today", "week", "month", "year")


def _zero_cl() -> dict:
    return {p: {"in": 0, "out": 0, "cw": 0, "cr": 0, "req": 0, "cost": 0.0} for p in PERIODS}


def _zero_cx() -> dict:
    return {p: {"in": 0, "out": 0, "cached": 0, "req": 0, "cost": 0.0} for p in PERIODS}


class TokenState:
    """
    Estado compartido entre los scanners (writers) y la UI (reader).
    Estructura: self.cl[period][field] y self.cx[period][field].
    Todos los accesos están protegidos por un lock.
    """

    def __init__(self):
        self.lock           = threading.Lock()
        self.started        = datetime.now()
        self.cl             = _zero_cl()
        self.cx             = _zero_cx()
        self.cl_log: list[str] = []
        self.cx_log: list[str] = []
        self.cl_last_model: str = ""
        self.cx_last_model: str = ""

    # ── escritura ─────────────────────────────────────────────────────────────

    def update(self, data: dict[str, dict], log: list[str],
               last_model: str = "") -> None:
        """data = {period: {in, out, cw, cr, req, cost}} para cada período de Claude."""
        with self.lock:
            for p in PERIODS:
                if p in data:
                    self.cl[p] = data[p]
            self.cl_log = log
            if last_model:
                self.cl_last_model = last_model

    def update_codex(self, data: dict[str, dict], log: list[str],
                     last_model: str = "") -> None:
        """data = {period: {in, out, cached, req, cost}} para cada período de Codex."""
        with self.lock:
            for p in PERIODS:
                if p in data:
                    self.cx[p] = data[p]
            self.cx_log = log
            if last_model:
                self.cx_last_model = last_model

    # ── lectura ───────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self.lock:
            out: dict = {}

            for p in PERIODS:
                cl = self.cl[p]
                cx = self.cx[p]

                cl_tok  = cl["in"] + cl["cw"] + cl["cr"] + cl["out"]
                cx_tok  = cx["in"] + cx["cached"] + cx["out"]
                cl_cost = cl["cost"]
                cx_cost = cx["cost"]

                # input_tok = lo que Anthropic cuenta contra el rate limit
                # (inp + cache_write + cache_read — todo lo que ocupa capacidad)
                out[f"cl_{p}_input_tok"] = cl["in"] + cl["cw"] + cl["cr"]
                out[f"cl_{p}_tok"]  = cl_tok
                out[f"cl_{p}_in"]   = cl["in"]
                out[f"cl_{p}_out"]  = cl["out"]
                out[f"cl_{p}_req"]  = cl["req"]
                out[f"cl_{p}_cost"] = cl_cost

                out[f"cx_{p}_tok"]  = cx_tok
                out[f"cx_{p}_in"]   = cx["in"]
                out[f"cx_{p}_out"]  = cx["out"]
                out[f"cx_{p}_req"]  = cx["req"]
                out[f"cx_{p}_cost"] = cx_cost

                out[f"total_{p}_cost"] = cl_cost + cx_cost
                out[f"total_{p}_req"]  = cl["req"] + cx["req"]

            combined = sorted(self.cl_log + self.cx_log)[-40:]
            out["log"]            = combined
            out["uptime"]         = str(datetime.now() - self.started).split(".")[0]
            out["cl_last_model"]  = self.cl_last_model
            out["cx_last_model"]  = self.cx_last_model
            return out

    def reset(self) -> None:
        with self.lock:
            self.started        = datetime.now()
            self.cl             = _zero_cl()
            self.cx             = _zero_cx()
            self.cl_log         = []
            self.cx_log         = []
            self.cl_last_model  = ""
            self.cx_last_model  = ""
