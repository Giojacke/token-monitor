import argparse
import json
import threading
from pathlib import Path

try:
    import tkinter as tk
except ImportError:
    raise SystemExit("[token-monitor] tkinter no disponible. Instala python3-tk.")

from .config import DEFAULT_DAILY_BUDGET, PROJECTS_DIR, CODEX_SESSIONS_DIR, CLAUDE_PRO_WEEKLY_LIMIT
from .detector import detect_or_cached, detect, print_detection, save_config, CONFIG_PATH
from .demo import demo_injector
from .scanner import TokenScanner
from .codex_scanner import CodexScanner
from .codex_status import CodexStatusPoller
from .wrapper import create_wrapper_scripts, WrapperScanner, wrapper_log_has_data, CODEX_LOG
from .gemini_scanner import GeminiScanner
from .copilot_scanner import CopilotScanner
from .log_writer import DailyLogger
from .i18n import set_lang
from .state import TokenState
from .tray import TrayManager, TRAY_AVAILABLE
from .ui import TokenMonitorApp


def _load_runtime_cfg(budget_arg: float) -> dict:
    """Lee config.json para overrides de límite/presupuesto guardados por SettingsWindow."""
    cfg = {
        "weekly_limit": CLAUDE_PRO_WEEKLY_LIMIT,
        "daily_budget": budget_arg,
    }
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text())
            if "claude_weekly_limit" in raw:
                cfg["weekly_limit"]  = int(raw["claude_weekly_limit"])
            if "claude_session_limit" in raw:
                cfg["session_limit"] = int(raw["claude_session_limit"])
            if "daily_budget" in raw:
                cfg["daily_budget"]  = float(raw["daily_budget"])
            if "weekly_reset_str" in raw:
                cfg["weekly_reset_str"]  = raw["weekly_reset_str"]
            if "sess_reset_min" in raw:
                cfg["sess_reset_min"]    = int(raw["sess_reset_min"])
            if "calibration_time" in raw:
                cfg["calibration_time"]  = raw["calibration_time"]
            if "calibration_factor" in raw:
                cfg["calibration_factor"] = float(raw["calibration_factor"])
            if "show_claude" in raw:
                cfg["show_claude"] = bool(raw["show_claude"])
            if "show_codex" in raw:
                cfg["show_codex"]  = bool(raw["show_codex"])
            if "show_gemini" in raw:
                cfg["show_gemini"] = bool(raw["show_gemini"])
            if "show_copilot" in raw:
                cfg["show_copilot"] = bool(raw["show_copilot"])
            if "copilot_plan" in raw:
                cfg["copilot_plan"] = raw["copilot_plan"]
            if "language" in raw:
                cfg["language"] = raw["language"]
            if "start_minimized" in raw:
                cfg["start_minimized"]   = bool(raw["start_minimized"])
            if "close_to_tray" in raw:
                cfg["close_to_tray"]     = bool(raw["close_to_tray"])
        except Exception:
            pass

    # Defaults: arrancar minimizado y cerrar a tray por defecto
    cfg.setdefault("start_minimized", True)
    cfg.setdefault("close_to_tray",   True)
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description="Token Monitor — Claude Code + Codex CLI")
    ap.add_argument("--demo",       action="store_true", help="Datos simulados")
    ap.add_argument("--budget",     type=float, default=DEFAULT_DAILY_BUDGET,
                    help=f"Presupuesto diario en USD (default: ${DEFAULT_DAILY_BUDGET})")
    ap.add_argument("--claude-dir", help="Directorio de proyectos Claude")
    ap.add_argument("--codex-dir",  help="Directorio de sesiones Codex")
    ap.add_argument("--redetect",   action="store_true",
                    help="Fuerza deteccion fresh ignorando cache")
    args = ap.parse_args()

    # ── 1. Deteccion (antes de cualquier ventana) ─────────────────────────────
    detection = detect() if args.redetect else detect_or_cached()
    if args.redetect:
        save_config(detection)
    print_detection(detection)

    # ── 2. Config mutable (límites/presupuesto) ───────────────────────────────
    runtime_cfg = _load_runtime_cfg(args.budget)

    # ── 3. Estado + scanners ──────────────────────────────────────────────────
    state        = TokenState()
    stop_ev      = threading.Event()
    codex_poller = None
    footer_msg   = ""

    if args.demo:
        print("[token-monitor] Modo DEMO activo")
        demo_injector(state)
        footer_msg = "demo mode"

    elif not detection.any_installed:
        print("[token-monitor] Sin herramientas detectadas")
        footer_msg = "ninguna herramienta detectada"

    else:
        claude_dir = Path(args.claude_dir) if args.claude_dir else PROJECTS_DIR
        codex_dir  = Path(args.codex_dir)  if args.codex_dir  else CODEX_SESSIONS_DIR

        watching = []

        # Claude Code
        if detection.show_claude:
            if claude_dir.exists():
                TokenScanner(claude_dir, state, stop_ev).start()
                watching.append("claude")
                if not detection.claude_has_logs:
                    print("[token-monitor] Claude -> esperando primera sesion...")
            else:
                print(f"[token-monitor] Claude  directorio no encontrado: {claude_dir}")

        # Codex CLI
        if detection.show_codex:
            # Crear wrapper scripts (con chmod +x en el .sh)
            wrappers   = create_wrapper_scripts()
            wrapper_sh = wrappers.get("sh")

            # Scanner JSONL (datos históricos + períodos)
            if codex_dir.exists():
                CodexScanner(codex_dir, state, stop_ev).start()

            # Rate-limit poller (codex /status + fallback JSONL)
            codex_poller = CodexStatusPoller(stop_ev)
            codex_poller.poll_now()
            codex_poller.start()

            # Wrapper log scanner (tokens en tiempo real)
            if wrapper_log_has_data():
                WrapperScanner(state, stop_ev).start()
                watching.append("codex")
                print(f"[token-monitor] Codex  -> watching {CODEX_LOG}")
            else:
                sh_path = str(wrapper_sh).replace("\\", "/").replace(
                    str(Path.home()).replace("\\", "/"), "~")
                print(f"[token-monitor] Codex  -> wrapper: {sh_path}")
                print(f"[token-monitor]            usa ese script en vez de 'codex'")
                watching.append(f"codex|{sh_path}")   # guarda ruta para el footer

        # Gemini CLI — descubre el directorio dinámicamente
        if detection.show_gemini:
            GeminiScanner(state, stop_ev).start()
            watching.append("gemini")
            print("[token-monitor] Gemini  -> watching ~/.gemini/tmp/<user>/chats/")

        # GitHub Copilot — escanea directorios de logs de la extensión VS Code
        if detection.show_copilot:
            CopilotScanner(state, stop_ev).start()
            watching.append("copilot")
            print(f"[token-monitor] Copilot -> watching {detection.copilot_log_path}")

        if watching:
            # Construir footer según estado del wrapper
            codex_entry = next((w for w in watching if w.startswith("codex|")), None)
            if codex_entry:
                sh_path    = codex_entry.split("|", 1)[1]
                footer_msg = f"para codex usa: {sh_path}"
            else:
                clean = [w.split("|")[0] for w in watching]
                footer_msg = "watching " + " + ".join(clean) + "..."

    # ── 4. UI ─────────────────────────────────────────────────────────────────
    set_lang(runtime_cfg.get("language", "es"))
    root = tk.Tk()

    # Ícono de ventana / taskbar
    try:
        from pathlib import Path as _Path
        _ico = _Path(__file__).parent / "assets" / "icon.ico"
        if _ico.exists():
            root.iconbitmap(str(_ico))
    except Exception:
        pass

    app  = TokenMonitorApp(
        root, state,
        daily_budget=runtime_cfg["daily_budget"],
        detection=detection,
        codex_poller=codex_poller,
        runtime_cfg=runtime_cfg,
        demo=args.demo,
    )
    app.set_status(footer_msg or "scanning...")

    # ── 5. System tray ────────────────────────────────────────────────────────
    if TRAY_AVAILABLE and not args.demo:
        tray = TrayManager(
            root        = root,
            state       = state,
            runtime_cfg = runtime_cfg,
            on_open     = app.show,
            on_settings = app._open_settings,
            on_quit     = app._quit,
        )
        tray.start()
        app.set_tray_manager(tray)
        print("[token-monitor] System tray activo")
    else:
        if not TRAY_AVAILABLE:
            print("[token-monitor] Tray no disponible — pip install pystray pillow")

    # ── 6. Arranque minimizado ────────────────────────────────────────────────
    if runtime_cfg.get("start_minimized", True) and TRAY_AVAILABLE and not args.demo:
        root.withdraw()
        print("[token-monitor] Arrancando minimizado en tray")

    # Guardar defaults de tray en config.json si no existen
    _ensure_tray_config()

    # ── 7. Daily CSV logger ───────────────────────────────────────────────────
    DailyLogger(state, stop_ev).start()
    print(f"[token-monitor] Logs diarios en: {Path.home() / '.token-monitor' / 'logs'}")

    try:
        root.mainloop()
    finally:
        stop_ev.set()


def _ensure_tray_config() -> None:
    """Escribe start_minimized y close_to_tray en config.json si no están."""
    try:
        raw = {}
        if CONFIG_PATH.exists():
            raw = json.loads(CONFIG_PATH.read_text())
        changed = False
        for key, default in [("start_minimized", True), ("close_to_tray", True)]:
            if key not in raw:
                raw[key] = default
                changed  = True
        if changed:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False))
    except Exception:
        pass


if __name__ == "__main__":
    main()
