from pathlib import Path

# ─── Rutas ────────────────────────────────────────────────────────────────────

PROJECTS_DIR         = Path.home() / ".claude" / "projects"
CODEX_SESSIONS_DIR   = Path.home() / ".codex"  / "sessions"
LOGS_DIR             = Path.home() / ".token-monitor" / "logs"
DEFAULT_DAILY_BUDGET     = 10.00        # USD — sobreescribible con --budget

# ─── Límites de plan Claude Pro ───────────────────────────────────────────────
# Anthropic cuenta inp + cache_write + cache_read (todo lo que ocupa rate limit).
# Ajustá CLAUDE_PRO_WEEKLY_LIMIT si tu plan tiene un límite diferente.
# Fuente: inferido de claude.ai/settings → Límites semanales.

CLAUDE_PRO_WEEKLY_LIMIT  = 17_700_000  # tokens/semana (Plan Pro) — ajustable en ⚙
CLAUDE_SESSION_WINDOW_H  = 5           # duración ventana de sesión en horas (5h = 300 min)

# ─── Precios por modelo Claude (USD / millón de tokens) ──────────────────────
# cache_w = input × 1.25  (+25 % sobre input)
# cache_r = input × 0.10  (-90 % sobre input)
# Actualizar aquí cuando Anthropic cambie precios.

CLAUDE_MODELS_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-7":   {"in": 5.00,  "cache_w": 6.25,  "cache_r": 0.50,  "out": 25.00},
    "claude-opus-4-6":   {"in": 5.00,  "cache_w": 6.25,  "cache_r": 0.50,  "out": 25.00},
    "claude-sonnet-4-6": {"in": 3.00,  "cache_w": 3.75,  "cache_r": 0.30,  "out": 15.00},
    "claude-haiku-4-5":  {"in": 1.00,  "cache_w": 1.25,  "cache_r": 0.10,  "out":  5.00},
    "claude-opus-4-1":   {"in": 15.00, "cache_w": 18.75, "cache_r": 1.50,  "out": 75.00},
    "claude-sonnet-3-7": {"in": 3.00,  "cache_w": 3.75,  "cache_r": 0.30,  "out": 15.00},
    "claude-haiku-3-5":  {"in": 0.80,  "cache_w": 1.00,  "cache_r": 0.08,  "out":  4.00},
    "default":           {"in": 3.00,  "cache_w": 3.75,  "cache_r": 0.30,  "out": 15.00},
}

# Conservados para compatibilidad con Codex y código legacy
CLAUDE_PRICE_IN      = 3.00  / 1_000_000
CLAUDE_PRICE_CACHE_W = 3.75  / 1_000_000
CLAUDE_PRICE_CACHE_R = 0.30  / 1_000_000
CLAUDE_PRICE_OUT     = 15.00 / 1_000_000

# ─── Precios por modelo Codex / OpenAI (USD / millón de tokens) ──────────────
# Actualizar aquí cuando OpenAI cambie precios.

CODEX_MODELS_PRICES: dict[str, dict[str, float]] = {
    "gpt-5.5":             {"in": 5.00,  "cached": 0.500,  "out": 30.00},
    "gpt-5.4":             {"in": 3.00,  "cached": 0.300,  "out": 15.00},
    "gpt-5.4-mini":        {"in": 0.50,  "cached": 0.050,  "out":  2.00},
    "gpt-5.3-codex":       {"in": 1.75,  "cached": 0.175,  "out": 14.00},
    "gpt-5.3-codex-spark": {"in": 1.75,  "cached": 0.175,  "out": 14.00},
    "gpt-5.2-codex":       {"in": 1.50,  "cached": 0.150,  "out": 12.00},
    "gpt-5.1-codex-mini":  {"in": 0.25,  "cached": 0.025,  "out":  2.00},
    "gpt-4o":              {"in": 2.50,  "cached": 1.250,  "out": 10.00},
    "gpt-4o-mini":         {"in": 0.15,  "cached": 0.075,  "out":  0.60},
    "gpt-4.1":             {"in": 2.00,  "cached": 0.500,  "out":  8.00},
    "gpt-4.1-mini":        {"in": 0.40,  "cached": 0.100,  "out":  1.60},
    "o3":                  {"in": 10.00, "cached": 2.500,  "out": 40.00},
    "o4-mini":             {"in": 1.10,  "cached": 0.275,  "out":  4.40},
    "default":             {"in": 2.50,  "cached": 0.500,  "out": 10.00},
}

# ─── Precios por modelo Gemini CLI (USD / millón de tokens) ──────────────────

GEMINI_MODELS_PRICES: dict[str, dict[str, float]] = {
    "gemini-3-flash-preview": {"in": 0.15,  "cached": 0.040, "out":  0.60},
    "gemini-2.5-pro":         {"in": 1.25,  "cached": 0.310, "out": 10.00},
    "gemini-2.5-flash":       {"in": 0.15,  "cached": 0.040, "out":  0.60},
    "gemini-2.0-flash":       {"in": 0.10,  "cached": 0.025, "out":  0.40},
    "default":                {"in": 1.25,  "cached": 0.310, "out": 10.00},
}

# Conservados para compatibilidad con código legacy
CODEX_PRICE_IN       = 1.10  / 1_000_000
CODEX_PRICE_CACHED   = 0.275 / 1_000_000
CODEX_PRICE_OUT      = 4.40  / 1_000_000

# ─── Timing ───────────────────────────────────────────────────────────────────

REFRESH_MS    = 1_000
SCAN_INTERVAL = 5
LOG_LINES     = 8

# ─── Ventana ──────────────────────────────────────────────────────────────────

WINDOW_W           = 400
WINDOW_H_EXPANDED  = 520
WINDOW_H_COLLAPSED = 32

# ─── Paleta ───────────────────────────────────────────────────────────────────

BG        = "#0c0c0c"
BG2       = "#141414"
BG3       = "#1c1c1c"
BORDER    = "#2a2a2a"
CLAUDE_C  = "#e07348"   # naranja — Claude Code
SESS_BAR  = "#f59e0b"   # ámbar   — barra sesión actual (igual que la web)
WEEK_BAR  = "#3b82f6"   # azul    — barra semanal (igual que la web)
CODEX_C   = "#34d399"   # verde   — Codex CLI
GEMINI_C  = "#4285f4"   # azul Google — Gemini CLI
DIM       = "#555555"
TEXT      = "#cccccc"
WHITE     = "#e8e8e8"
