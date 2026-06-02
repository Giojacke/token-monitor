<div align="center">
  <img src="assets/banner.png" alt="Token Monitor" width="600"/>

  # Token Monitor

  **Monitor en tiempo real del consumo de tokens de Claude Code, Codex CLI, Gemini CLI y GitHub Copilot**

  ![version](https://img.shields.io/badge/version-1.0.0-green)
  ![license](https://img.shields.io/badge/license-MIT-green)
  ![python](https://img.shields.io/badge/python-3.8+-green)
  ![platform](https://img.shields.io/badge/platform-windows%20%7C%20mac%20%7C%20linux-green)
</div>

---

## ¿Qué es esto?

Una pantalla flotante de escritorio que lee en tiempo real los logs de **Claude Code**, **Codex CLI**, **Gemini CLI** y **GitHub Copilot** y muestra:

- Tokens consumidos por sesión (ventana de 5h) y acumulados por día, semana, mes y año
- Modelo detectado automáticamente (`claude-sonnet-4-6`, `gpt-5.4`, `gemini-2.5-pro`, etc.)
- Costo estimado en dólares usando precios reales de API por modelo
- Barra de uso calibrable contra `claude.ai/settings` con factor de corrección
- System tray de Windows con tooltip de uso en tiempo real — arranca minimizado por defecto
- Scroll vertical para agregar más proveedores sin romper el layout
- **Logs diarios en CSV** guardados automáticamente en `~/.token-monitor/logs/`
- **Interfaz en español e inglés** — cambiable en ⚙ sin reiniciar

---

## Instalación

```bash
git clone https://github.com/CodHector/token-monitor
cd token-monitor
pip install -r requirements.txt
python -m token_monitor
```

---

## Uso

```bash
# Modo demo — datos simulados sin herramientas instaladas
python -m token_monitor --demo

# Claude Code solamente
python -m token_monitor --claude-dir ~/.claude/projects/

# Codex CLI solamente
python -m token_monitor --codex-dir ~/.codex/sessions/

# Los dos juntos (modo por defecto)
python -m token_monitor

# Presupuesto diario personalizado en USD
python -m token_monitor --budget 20

# Forzar re-detección de herramientas instaladas
python -m token_monitor --redetect
```

> Al arrancar, el monitor se minimiza automáticamente al system tray. El ícono queda visible con un tooltip de uso en tiempo real.

---

## ¿Cómo funciona?

### Claude Code

Claude Code escribe cada request en archivos `.jsonl` dentro de `~/.claude/projects/`. El monitor los lee cada 5 segundos **sin tocar ninguna API** — solo lectura de logs locales.

Cada línea tiene el campo `message.model` (modelo usado) y `message.usage` (tokens de input, output y cache). El monitor acumula los **output tokens** como métrica principal porque son los únicos que no se repiten entre requests a diferencia del contexto de input acumulado.

La barra de sesión se calibra contra `claude.ai/settings` con un **factor de corrección** ajustable desde ⚙ sin reiniciar el monitor.

### Codex CLI

Codex escribe sus sesiones en `~/.codex/sessions/**/rollout-*.jsonl`. El monitor detecta el modelo en los eventos `turn_context` (campo `payload.model`) y acumula tokens desde los eventos `token_count` usando `last_token_usage` — no `total_token_usage` — para evitar doble conteo al sumar línea a línea.

### Gemini CLI

Gemini CLI escribe sus chats en `~/.gemini/tmp/<usuario>/chats/session-*.jsonl`. El monitor detecta dinámicamente el subdirectorio del usuario (con fallback automático para entornos corporativos o Docker).

El JSONL de Gemini usa un patrón de append-update donde la misma entrada puede aparecer múltiples veces. El monitor deduplica por `id` para evitar doble conteo.

### GitHub Copilot

GitHub Copilot (extensión de VS Code) escribe logs en:

- **Windows:** `%APPDATA%\GitHub Copilot\` y `%APPDATA%\Code\User\globalStorage\github.copilot-chat\`
- **Mac:** `~/Library/Application Support/GitHub Copilot/`
- **Linux:** `~/.config/github-copilot/`

El monitor lee archivos `.json` y `.jsonl` de esos directorios buscando los campos `model`, `token_usage` (OpenAI) o `tokens` (Anthropic/otros). Los costos mostrados son el **equivalente en API** — el costo real para el usuario es la suscripción mensual de Copilot.

---

## Logs diarios

El monitor guarda un resumen diario en `~/.token-monitor/logs/YYYY-MM-DD.txt` con formato CSV:

```
provider,model,date,tokens_in,tokens_out,tokens_cached,requests,cost_usd
claude,sonnet-4-6,2026-06-02,284231,3667,272564,15,0.055005
gemini,gemini-3-flash-preview,2026-06-02,55944,502,22626,9,0.000433
```

El archivo se actualiza cada 60 segundos (sobreescribe el del día actual). Ideal para auditoría o importar a hojas de cálculo.

---

## Estructura del proyecto

```text
token_monitor/
├── __main__.py        Bootstrap — detección, scanners, UI, tray
├── config.py          Constantes, precios por modelo, colores, tamaños
├── detector.py        Detección de Claude Code, Codex CLI y Gemini CLI
├── parser.py          Parseo de JSONL y cálculo de costo por modelo
├── state.py           Estado compartido thread-safe entre scanners y UI
├── scanner.py         Scanner de JSONL de Claude Code
├── codex_scanner.py   Scanner de JSONL de Codex CLI
├── codex_status.py    Poller de `codex /status` para rate-limits en vivo
├── gemini_scanner.py  Scanner de JSONL de Gemini CLI
├── copilot_scanner.py Scanner de JSON/JSONL de GitHub Copilot
├── wrapper.py         Generación de scripts wrapper para Codex en tiempo real
├── ui.py              Interfaz Tkinter flotante con scroll
├── tray.py            Integración system tray
├── settings_ui.py     Ventana de configuración y calibración
├── i18n.py            Internacionalización — español e inglés
├── log_writer.py      Logger diario en CSV (~/.token-monitor/logs/)
├── demo.py            Inyector de datos demo
└── assets/            Íconos de la aplicación
assets/
└── banner.png         Banner del proyecto
```

---

## Modelos soportados

### Claude (Anthropic) — precios USD por millón de tokens

| Modelo | Input | Cache Write | Cache Read | Output |
|--------|------:|------------:|-----------:|-------:|
| claude-opus-4-7 / 4-6 | $5.00 | $6.25 | $0.50 | $25.00 |
| claude-sonnet-4-6 | $3.00 | $3.75 | $0.30 | $15.00 |
| claude-haiku-4-5 | $1.00 | $1.25 | $0.10 | $5.00 |
| claude-opus-4-1 | $15.00 | $18.75 | $1.50 | $75.00 |
| claude-sonnet-3-7 | $3.00 | $3.75 | $0.30 | $15.00 |
| claude-haiku-3-5 | $0.80 | $1.00 | $0.08 | $4.00 |

### Codex / OpenAI — precios USD por millón de tokens

| Modelo | Input | Cached | Output |
|--------|------:|-------:|-------:|
| gpt-5.5 | $5.00 | $0.50 | $30.00 |
| gpt-5.4 | $3.00 | $0.30 | $15.00 |
| gpt-5.4-mini | $0.50 | $0.05 | $2.00 |
| gpt-5.3-codex / spark | $1.75 | $0.175 | $14.00 |
| gpt-5.2-codex | $1.50 | $0.15 | $12.00 |
| gpt-5.1-codex-mini | $0.25 | $0.025 | $2.00 |
| gpt-4o | $2.50 | $1.25 | $10.00 |
| gpt-4o-mini | $0.15 | $0.075 | $0.60 |
| gpt-4.1 | $2.00 | $0.50 | $8.00 |
| gpt-4.1-mini | $0.40 | $0.10 | $1.60 |
| o3 | $10.00 | $2.50 | $40.00 |
| o4-mini | $1.10 | $0.275 | $4.40 |

### Gemini CLI (Google) — precios USD por millón de tokens

| Modelo | Input | Cached | Output |
|--------|------:|-------:|-------:|
| gemini-3-flash-preview | $0.15 | $0.040 | $0.60 |
| gemini-2.5-pro | $1.25 | $0.310 | $10.00 |
| gemini-2.5-flash | $0.15 | $0.040 | $0.60 |
| gemini-2.0-flash | $0.10 | $0.025 | $0.40 |

### GitHub Copilot — precios USD por millón de tokens (equiv. API)

| Modelo | Input | Cached | Output |
|--------|------:|-------:|-------:|
| gpt-5.1 / gpt-5.1-codex-mini | $0.25 | $0.025 | $2.00 |
| gpt-5.3-codex | $1.75 | $0.175 | $14.00 |
| gpt-4o | $2.50 | $1.250 | $10.00 |
| gpt-4o-mini | $0.15 | $0.075 | $0.60 |
| gpt-4.1 | $2.00 | $0.500 | $8.00 |
| claude-sonnet-4.5 | $3.00 | $0.300 | $15.00 |
| claude-haiku-3.5 | $0.80 | $0.080 | $4.00 |

> Los precios viven en `token_monitor/config.py` como diccionarios. Actualizar un precio = una línea de código.

---

## Calibración

Si el porcentaje no coincide con `claude.ai/settings`:

1. Abre ⚙ en el monitor
2. Sección **"Calibrar límites"**: ingresa el % actual de la web → recalcula los límites en tokens desde cero
3. Sección **"Recalibrar factor"**: si ya tienes límites calibrados, ajusta el multiplicador fino sin cambiarlos

---

## Idioma

La interfaz soporta **español** e **inglés**. Para cambiar:

1. Abre ⚙ en el monitor
2. Sección **IDIOMA** → selecciona `es` o `en`
3. Guarda — el cambio se aplica en el próximo arranque

Para agregar un idioma nuevo, añade una clave en el dict `TEXTOS` de `token_monitor/i18n.py` con el mismo conjunto de keys.

---

## Roadmap

- [x] Gemini CLI
- [x] GitHub Copilot
- [ ] Cursor
- [ ] Notificaciones de alerta al cruzar umbrales configurables
- [ ] Exportar historial a CSV *(logs diarios ya disponibles en `~/.token-monitor/logs/`)*
- [ ] Tests automatizados de parsers

---

## Contribuir

1. Fork del repo
2. `git checkout -b feature/nueva-ia`
3. Para agregar un proveedor nuevo, implementa un scanner siguiendo el patrón de `scanner.py`, `codex_scanner.py`, `gemini_scanner.py` o `copilot_scanner.py`
4. Los precios del modelo nuevo van en `config.py` como dict `{modelo: {in, cached, out}}`
5. Agrega las claves de traducción necesarias en `i18n.py` (español e inglés)
6. PR con descripción de qué IA agregaste y cómo detectaste el modelo en sus logs locales

---

## Licencia

MIT — hecho con ❤️ para la comunidad dev hispana
