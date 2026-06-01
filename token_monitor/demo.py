import random
import threading
import time
from datetime import datetime

from .state import TokenState


def demo_injector(state: TokenState) -> None:
    """Simula tráfico de Claude y Codex con datos incrementales por período."""

    def _run() -> None:
        tick = 0
        while True:
            time.sleep(random.uniform(1.5, 3.5))
            tick += 1
            ts = datetime.now().strftime("%H:%M:%S")

            state.update(
                data={
                    "sess":  {"in": tick*45_000,  "out": tick*1_200,  "cw": tick*5_000,  "cr": tick*20_000,  "req": tick},
                    "today": {"in": tick*120_000,  "out": tick*3_000,  "cw": tick*15_000, "cr": tick*50_000,  "req": tick*3},
                    "week":  {"in": tick*600_000,  "out": tick*15_000, "cw": tick*80_000, "cr": tick*250_000, "req": tick*15},
                    "month": {"in": tick*2_000_000,"out": tick*60_000, "cw": tick*300_000,"cr": tick*900_000, "req": tick*50},
                    "year":  {"in": tick*8_000_000,"out": tick*250_000,"cw": tick*1_200_000,"cr":tick*3_500_000,"req": tick*200},
                },
                log=[f"[{ts}]  in={45_000:,}  out={1_200:,}"] * min(tick, 5),
            )
            state.update_codex(
                data={
                    "sess":  {"in": tick*10_000, "out": tick*800,  "cached": tick*3_000,  "req": tick},
                    "today": {"in": tick*25_000, "out": tick*2_000, "cached": tick*8_000,  "req": tick*2},
                    "week":  {"in": tick*120_000,"out": tick*9_000, "cached": tick*40_000, "req": tick*9},
                    "month": {"in": tick*400_000,"out": tick*30_000,"cached": tick*130_000,"req": tick*30},
                    "year":  {"in": tick*1_500_000,"out": tick*120_000,"cached": tick*500_000,"req": tick*120},
                },
                log=[f"[{ts}] [cx]  in={10_000:,}  out={800:,}"] * min(tick, 3),
            )

    threading.Thread(target=_run, daemon=True).start()
