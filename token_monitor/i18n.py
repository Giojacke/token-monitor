"""
Internacionalización del Token Monitor.
Para agregar un idioma nuevo: añadir una clave con el mismo conjunto de keys.
Para cambiar en tiempo real: set_lang("en") + llamar _apply_language() en la UI.
"""

current_lang: str = "es"

TEXTOS: dict[str, dict[str, str]] = {
    "es": {
        # ── Header / título ──────────────────────────────────────────────────
        "title":               "TOKEN MONITOR",
        "live":                "● EN VIVO",
        # ── Barras Claude ────────────────────────────────────────────────────
        "session":             "Sesión actual",
        "weekly":              "Semanal — todos los modelos",
        "resets_in":           "reset en",
        "resets_on":           "Se restablece",
        "equiv_api":           "equiv. API:",
        "calibrate_hint":      "calibrar en ⚙",
        # ── Tabla de períodos ────────────────────────────────────────────────
        "today":               "HOY",
        "week":                "SEM",
        "month":               "MES",
        "year":                "AÑO",
        "tok_col":             "tok",
        # ── Tarjetas de totales ──────────────────────────────────────────────
        "total_today":         "hoy total",
        "total_week":          "semana",
        "total_month":         "mes",
        "total_year":          "año",
        # ── Activity log ─────────────────────────────────────────────────────
        "activity_log":        "ACTIVITY LOG",
        # ── Footer ───────────────────────────────────────────────────────────
        "reset":               "reset",
        "scanning":            "escaneando...",
        # ── Proveedores ──────────────────────────────────────────────────────
        "plan_pro":            "Plan Pro",
        "chatgpt_plus":        "ChatGPT Plus",
        "google_ai":           "Google AI",
        "unknown":             "desconocido",
        "no_tools_msg":        "no se detectó claude code ni codex cli",
        "no_tools_hint":       "instala alguno y reinicia el monitor",
        # ── Ventana de configuración — secciones ─────────────────────────────
        "config_title":        "CONFIGURACIÓN",
        "providers":           "PROVEEDORES VISIBLES",
        "providers_hint":      "Marca los que quieres ver en el monitor.",
        "claude_code":         "Anthropic — Claude Code",
        "codex_cli":           "OpenAI — Codex CLI",
        "gemini_cli":          "Google — Gemini CLI",
        "copilot_cli":             "GitHub — Copilot",
        "github_enterprise":       "GitHub Enterprise",
        "copilot_plan_title":      "PLAN GITHUB COPILOT",
        "copilot_plan_hint":       "Selecciona tu plan para calibrar la barra de uso.",
        "copilot_plan_note_free":  "Barra: requests este mes / {chat} (límite free).\nCompletions: {completions}/mes.",
        "copilot_plan_note_pro":   "Barra: AI credits gastados / ${credits} este mes.",
        "copilot_plan_note_enterprise": "Sin límite fijo — barra muestra tu consumo individual.",
        "copilot_plan_note_unknown":    "Selecciona tu plan para ver la barra correcta.",
        "copilot_enterprise_note": "tu aporte individual a la licencia empresa",
        "language":            "IDIOMA",
        "calibrate":           "CALIBRAR DESDE claude.ai/settings",
        "calibrate_desc":      "Ingresa los valores actuales que muestra la web.\nEl monitor calcula los límites reales de tu plan.",
        "session_pct":         "Sesión actual  (%)",
        "session_reset_min":   "Reset sesión en (min)",
        "weekly_pct":          "Semanal        (%)",
        "weekly_reset_time":   "Reset semanal (ej. mar 15:00)",
        "calibrate_btn":       "Calibrar límites",
        "recalibrate":         "RECALIBRAR FACTOR",
        "recalibrate_desc":    "Abre claude.ai/settings y dime los % actuales.\nAjusta el factor sin recalcular los límites.",
        "recalibrate_btn":     "Recalibrar factor",
        "general":             "AJUSTES GENERALES",
        "weekly_limit":        "Límite semanal (M tok)",
        "daily_budget":        "Presupuesto diario (USD)",
        "save":                "Guardar",
        "saved":               "Guardado",
        "visibility":          "Visibilidad actualizada",
        # ── Mensajes de error / estado ───────────────────────────────────────
        "err_invalid":         "Error: valores inválidos",
        "err_pct_pos":         "Los % deben ser > 0",
        "err_no_5h":           "Sin output tokens en las últimas 5h.\nUsa Claude Code un momento y reintenta.",
        "err_no_week":         "Sin output tokens esta semana.\nEspera 5s y reintenta.",
        "err_calibrate_first": "Calibra los límites primero (botón arriba).",
        "err_no_sess":         "Sin output tokens de sesión.\nUsa Claude Code y reintenta.",
        "calibrated_ok":       "Calibrado",
        "calibrated_detail":   "sesión={sess}\nsemanal={week}",
        "factor_result":       "Factor: x{f}  ({before:.1f}%→{after:.1f}%)",
    },
    "en": {
        # ── Header / título ──────────────────────────────────────────────────
        "title":               "TOKEN MONITOR",
        "live":                "● LIVE",
        # ── Barras Claude ────────────────────────────────────────────────────
        "session":             "Current session",
        "weekly":              "Weekly — all models",
        "resets_in":           "resets in",
        "resets_on":           "Resets on",
        "equiv_api":           "equiv. API:",
        "calibrate_hint":      "calibrate in ⚙",
        # ── Tabla de períodos ────────────────────────────────────────────────
        "today":               "TODAY",
        "week":                "WEEK",
        "month":               "MONTH",
        "year":                "YEAR",
        "tok_col":             "tok",
        # ── Tarjetas de totales ──────────────────────────────────────────────
        "total_today":         "today total",
        "total_week":          "week",
        "total_month":         "month",
        "total_year":          "year",
        # ── Activity log ─────────────────────────────────────────────────────
        "activity_log":        "ACTIVITY LOG",
        # ── Footer ───────────────────────────────────────────────────────────
        "reset":               "reset",
        "scanning":            "scanning...",
        # ── Proveedores ──────────────────────────────────────────────────────
        "plan_pro":            "Pro Plan",
        "chatgpt_plus":        "ChatGPT Plus",
        "google_ai":           "Google AI",
        "unknown":             "unknown",
        "no_tools_msg":        "claude code or codex cli not detected",
        "no_tools_hint":       "install one and restart the monitor",
        # ── Ventana de configuración — secciones ─────────────────────────────
        "config_title":        "SETTINGS",
        "providers":           "VISIBLE PROVIDERS",
        "providers_hint":      "Select which providers to show.",
        "claude_code":         "Anthropic — Claude Code",
        "codex_cli":           "OpenAI — Codex CLI",
        "gemini_cli":          "Google — Gemini CLI",
        "copilot_cli":             "GitHub — Copilot",
        "github_enterprise":       "GitHub Enterprise",
        "copilot_plan_title":      "GITHUB COPILOT PLAN",
        "copilot_plan_hint":       "Select your plan to calibrate the usage bar.",
        "copilot_plan_note_free":  "Bar: requests this month / {chat} (free limit).\nCompletions: {completions}/month.",
        "copilot_plan_note_pro":   "Bar: AI credits spent / ${credits} this month.",
        "copilot_plan_note_enterprise": "No fixed limit — bar shows your individual usage.",
        "copilot_plan_note_unknown":    "Select your plan to see the correct bar.",
        "copilot_enterprise_note": "your individual contribution to the enterprise license",
        "language":            "LANGUAGE",
        "calibrate":           "CALIBRATE FROM claude.ai/settings",
        "calibrate_desc":      "Enter the current values shown on the web.\nThe monitor calculates your plan's real limits.",
        "session_pct":         "Current session (%)",
        "session_reset_min":   "Session reset in (min)",
        "weekly_pct":          "Weekly         (%)",
        "weekly_reset_time":   "Weekly reset (e.g. tue 15:00)",
        "calibrate_btn":       "Calibrate limits",
        "recalibrate":         "RECALIBRATE FACTOR",
        "recalibrate_desc":    "Open claude.ai/settings and enter the current %.\nAdjusts factor without recalculating limits.",
        "recalibrate_btn":     "Recalibrate factor",
        "general":             "GENERAL SETTINGS",
        "weekly_limit":        "Weekly limit (M tok)",
        "daily_budget":        "Daily budget (USD)",
        "save":                "Save",
        "saved":               "Saved",
        "visibility":          "Visibility updated",
        # ── Mensajes de error / estado ───────────────────────────────────────
        "err_invalid":         "Error: invalid values",
        "err_pct_pos":         "Percentages must be > 0",
        "err_no_5h":           "No output tokens in the last 5h.\nUse Claude Code briefly and retry.",
        "err_no_week":         "No output tokens this week.\nWait 5s and retry.",
        "err_calibrate_first": "Calibrate limits first (button above).",
        "err_no_sess":         "No session output tokens.\nUse Claude Code and retry.",
        "calibrated_ok":       "Calibrated",
        "calibrated_detail":   "session={sess}\nweekly={week}",
        "factor_result":       "Factor: x{f}  ({before:.1f}%→{after:.1f}%)",
    },
}


def t(key: str) -> str:
    """Retorna el texto en el idioma activo. Fallback al key si no existe."""
    return TEXTOS.get(current_lang, TEXTOS["es"]).get(key, key)


def set_lang(lang: str) -> None:
    global current_lang
    if lang in TEXTOS:
        current_lang = lang


def get_lang() -> str:
    return current_lang
