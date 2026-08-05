# Pi Agent Harness Environment & Setup Guide

Automated provisioning, automatic tool-schema sanitization, on-demand model sync, and extension catalog for Pi Agent.
Works on **Windows, Linux, and WSL**.

---

## 🚀 Quick Start (New Computer Setup)

To setup or restore Pi Agent settings, extensions, and configurations on a new machine:

```bash
node setup-pi-agent.js
```

### Target selection (`--target`)

Run the script from inside **WSL** to provision either the WSL side (default) or the
**Windows** side of the same machine:

```bash
node setup-pi-agent.js                     # default: wsl (when running inside WSL)
node setup-pi-agent.js --target wsl        # explicit: provision the WSL side
node setup-pi-agent.js --target windows    # provision the Windows side (from WSL)
node setup-pi-agent.js --target windows --no-install   # config files only
```

- **Default** = `wsl` inside WSL, `windows` on a native Windows host, `native` elsewhere.
- `--target windows` from WSL resolves the Windows user profile via `%USERPROFILE%`
  (`/mnt/c/Users/<user>`), writes all configs there (`C:\Users\<user>\.pi`), and runs
  installs through Windows interop (`cmd.exe`/`powershell.exe` full paths — Windows exes
  are not on the WSL `PATH`).
- rtk installs as `rtk.exe` into `%USERPROFILE%\.local\bin` (added to the Windows user
  PATH); `agent-browser` installs via Windows `npm -g`; Chrome for Testing lands in
  `%USERPROFILE%\.agent-browser\browsers`.
- If `pi` itself is missing on the Windows side, the script bootstraps it first
  (`npm install -g @earendil-works/pi-coding-agent`), then installs the configured packages.

The script will also:

- **Auto-install the `rtk` binary** (Rust token killer) if missing — official installer on
  Linux/macOS/WSL, GitHub release download on Windows — and make sure `~/.local/bin` is on
  PATH for future shells.
- **Auto-install `agent-browser`** (CLI via `npm -g`) and run `agent-browser install` to
  download Chrome for Testing, so the `agent_browser` tool works out of the box. Warns if
  `ffmpeg` is missing (only needed for screen recording).
- **Never modifies npm-installed packages** (`pi-agent-browser-native`, `pi-rtk-optimizer`,
  ...). All customization lives in separate top-level files under
  `~/.pi/agent/extensions/`, so future package updates cannot overwrite our code.

### Provide API keys / URLs during setup

Pass values with `--env KEY=value` (repeatable) or export them in the shell. The merge is smart:

| Existing value in `~/.pi/.env` | What happens |
| :--- | :--- |
| key missing | written (placeholder or provided value) |
| blank (`""`) | **overwritten** (placeholder or provided value) |
| demo/default placeholder (e.g. the sample 9Router URL) | **replaced** when a real value is provided |
| real value | **preserved**, never clobbered — but normalized to quoted form (`KEY="value"`) if it was typed naked |

```bash
node setup-pi-agent.js \
  --env NINE_ROUTER=sk-your-9router-key \
  --env NINE_ROUTER_BASE_URL=https://your-real-proxy.example.com/v1 \
  --env TAVILY_API_KEY=tvly-your-key \
  --env EXA_API_KEY=sk-exa-... \
  --env BRAVE_API_KEY=...
```

### Managed API keys (tool/extension keys only)

> Model/provider API keys (ANTHROPIC, OPENAI, GEMINI, DEEPSEEK, ...) are **intentionally not**
> managed here — configure those via `pi /login` or `~/.pi/agent/auth.json`. This script only
> manages **tool/extension keys**, so it stays orthogonal to your model access.

All keys below are written to `~/.pi/.env` and automatically wired into the configs that use
them (`web-search.json` readers, agent-browser config, `/9router-sync`). Fill them via
`--env KEY=value`, export in the shell, or edit `~/.pi/.env` directly and re-run:

| Group | Keys | Used by |
| :--- | :--- | :--- |
| Web search | `TAVILY_API_KEY`, `BRAVE_API_KEY`, `EXA_API_KEY`, `PARALLEL_API_KEY`, `TINYFISH_API_KEY`, `SEARCH1API_KEY`, `SEARCHINFINITY_API_KEY`, `QUERIT_API_KEY`, `SERPDIVE_API_KEY`, `KAGI_API_KEY`, `OLLAMA_API_KEY`, `SERPBASE_API_KEY`, `ANYSEARCH_API_KEY`, `BRIGHTDATA_API_KEY` (+ `BRIGHTDATA_SERP_ZONE`, `BRIGHTDATA_UNLOCKER_ZONE`), `FIRECRAWL_API_KEY`, `PERPLEXITY_API_KEY` | `pi-web-access` search providers |
| 9Router proxy | `NINE_ROUTER`, `NINE_ROUTER_BASE_URL` | `/9router-sync` model sync |
| agent-browser providers | `BROWSERLESS_API_KEY`, `BROWSERBASE_API_KEY`, `BROWSER_USE_API_KEY`, `KERNEL_API_KEY` | `agent_browser` cloud providers |
| agent-browser web search | `EXA_API_KEY`, `BRAVE_API_KEY` (shared) | `agent_browser_web_search` companion |

One key is **auto-generated**, not managed as a blank placeholder:

- `AGENT_BROWSER_ENCRYPTION_KEY` — random 64-char hex (AES-256-GCM) generated on first run
  for agent-browser state encryption; kept stable on re-runs, never clobbered if you set one.

### Config-only mode

Skip binary/package installs and only (re)generate config files:

```bash
node setup-pi-agent.js --no-install
```

---

## 🧹 Removing the old always-on 9Router hook (legacy machines)

Older versions of this repo shipped an extension (`9router-discovery.ts`) that synced models
**on every Pi launch** via `session_start` hooks. The new setup script migrates this
automatically (deletes the file + settings entry, installs the on-demand command extension).

If you need to remove the old hook manually **before** re-running setup, use:

```bash
node remove-9router-hook.js
```

This deletes both halves of the hook:

1. `~/.pi/agent/extensions/9router-discovery.ts` (the extension file)
2. the `"extensions/9router-discovery.ts"` entry in the `packages` array of
   `~/.pi/agent/settings.json` (and project `.pi/settings.json` if present)

It backs up `settings.json` before editing, handles both string and object-form package
entries, is safe to re-run, and works on Windows / Linux / WSL.

---

## 🔑 Post-Installation Credentials Setup

After running `node setup-pi-agent.js`, populate your API keys in the generated environment files:

### 1. `~/.pi/.env`

```env
# --- Web search providers ---
TAVILY_API_KEY="tvly-your-key-here"
BRAVE_API_KEY=""
EXA_API_KEY=""
PARALLEL_API_KEY=""
TINYFISH_API_KEY=""
SEARCH1API_KEY=""
SEARCHINFINITY_API_KEY=""
QUERIT_API_KEY=""
SERPDIVE_API_KEY=""
KAGI_API_KEY=""
OLLAMA_API_KEY=""
SERPBASE_API_KEY=""
ANYSEARCH_API_KEY=""
BRIGHTDATA_API_KEY=""
BRIGHTDATA_SERP_ZONE=""
BRIGHTDATA_UNLOCKER_ZONE=""
FIRECRAWL_API_KEY=""
PERPLEXITY_API_KEY=""
# --- 9Router proxy ---
NINE_ROUTER="sk-your-9router-key-here"
NINE_ROUTER_BASE_URL="https://your-real-proxy.example.com/v1"
# --- agent-browser cloud providers ---
BROWSERLESS_API_KEY=""
BROWSERBASE_API_KEY=""
BROWSER_USE_API_KEY=""
KERNEL_API_KEY=""
# --- auto-generated on first run ---
AGENT_BROWSER_ENCRYPTION_KEY="<64-hex chars, generated>"
```

### 2. `~/.pi/agent/auth.json`

```json
{
  "opencode": {
    "type": "api_key",
    "key": "your-opencode-key"
  },
  "9router": {
    "type": "api_key",
    "key": "sk-your-9router-key-here"
  }
}
```

---

## 🚦 Gemini tool-schema sanitizer + 9Router sync (`/9router-sync`)

### Automatic Gemini sanitizer (no manual step)

The extension registers a `before_provider_request` hook that fires right before EVERY
provider request but **only acts on Gemini-family models** (`gemini-*`, `gemini/gemini-*`,
`ag/gemini-*` — native Gemini, 9Router, and Antigravity). For those models it deep-strips
internal TypeBox metadata keys (`~optional`, `~kind`, `~readonly`) from tool schemas
embedded in the payload, fixing `HTTP 400: Unknown name "~optional"` errors. Non-Gemini
providers (deepseek, etc.) pass through untouched. This matters for tools whose schemas are
built with `Type.Optional(<raw JSON>)`, e.g. `mcpScript.timeoutMs`, `mcp.limit`, `mcp.offset`
in `pi-mcp-adapter` — TypeBox marks those with an *enumerable* `~optional` key that survives
JSON serialization.

> Why `gemini/gemini-3.6-flash` fails but `ag/gemini-3.6-flash-high` seemed to work:
> both route through the same 9Router proxy to the same strict Gemini/Antigravity backend,
> and both reject `~optional` identically. The difference was whether `~optional` was present
> in the tool schemas at request time (e.g. after MCP tools were registered). The automatic
> sanitizer removes the key for every Gemini request regardless.

### Manual model catalog sync (`/9router-sync`)

Run the slash command to sync the 9Router model list into `~/.pi/agent/models.json`:

```
/9router-sync
```

- Fetches `GET {NINE_ROUTER_BASE_URL}/models` with the `NINE_ROUTER` key from `~/.pi/.env`.
- Writes the `9router` provider + models into `~/.pi/agent/models.json`
  (`api: openai-completions`, per-model `reasoning` / `input` / `contextWindow` / `maxTokens`).
- Also strips `~optional`/`~kind`/`~readonly` from registered tool schemas in place (belt and
  suspenders on top of the automatic per-request strip).
- Reports how many models were synced and how many tool schemas were sanitized.

> [!NOTE]
> Run `/9router-sync` after Pi starts (or after `/reload`), or any time your 9Router model
> catalog changes. You do **not** need it to fix `~optional` errors — the automatic Gemini
> sanitizer handles those on every request.

---

## 📦 Installed Packages & Extensions

### Standard Packages (`settings.json`)

| Package Name | Purpose / Functionality |
| :--- | :--- |
| **`pi-mcp-adapter`** | Integrates Model Context Protocol (MCP) servers and tools into Pi harness. |
| **`pi-web-access`** | Comprehensive web search, webpage scraping, YouTube transcript/frame analysis, PDF reading, and multi-provider fallback routing (SearXNG, Exa, Brave, Tavily, Gemini). |
| **`pi-subagents`** | Enables spawning, communicating with, and orchestrating sub-agents concurrently. |
| **`pi-lens`** | Language Server Protocol (LSP) diagnostics, read-guard file enforcement, and inline code checks. |
| **`@juicesharp/rpiv-ask-user-question`** | Renders interactive multi-choice question prompts for user decision input. |
| **`@ff-labs/pi-fff`** | Fast File Finder (FFF) using frecency-based file search and history ranking. |
| **`@juicesharp/rpiv-todo`** | Interactive persistent session task list and todo tracker. |
| **`pi-agent-browser-native`** | Native headless browser automation and web page interaction capability. |
| **`pi-rtk-optimizer`** | RTK command rewriting + tool output compaction (needs the `rtk` binary — auto-installed by setup). |
| **`pi-sidebar-tui`** | Sidebar TUI panel for Pi (session/context overview). |
| **`opencode-pi`** | OpenCode provider integration for Pi. |

### External binaries managed by setup

| Binary | Needed by | Auto-installed by setup |
| :--- | :--- | :--- |
| `rtk` (`~/.local/bin/rtk`) | `pi-rtk-optimizer` command rewriting | ✅ official installer / GitHub release |
| `agent-browser` (npm global) | `pi-agent-browser-native` | ✅ `npm install -g agent-browser` |
| Chrome for Testing (`~/.agent-browser/browsers/`) | `agent_browser` tool launch | ✅ `agent-browser install` |
| `ffmpeg` | browser screen recording (`record stop`) | ⚠️ warning only (apt/brew/winget) |

---

## 🛠️ Custom Local Extensions

### `9router-sync.ts` (`~/.pi/agent/extensions/9router-sync.ts`)

- **Automatic Gemini sanitizer**: hooks `before_provider_request` and strips internal TypeBox
  metadata keys (`~optional`, `~kind`, `~readonly`) from tool schemas **only for
  Gemini-family models** (`gemini-*`, `gemini/gemini-*`, `ag/gemini-*` — native Gemini,
  9Router, Antigravity), preventing `HTTP 400: Unknown name "~optional"` errors. Non-Gemini
  providers pass through untouched.
- **Model sync**: `/9router-sync` slash command syncs the 9Router model catalog into
  `~/.pi/agent/models.json` and sanitizes registered tool schemas in place.
- **Reasoning Token Support**: configures provider compatibility options allowing live
  reasoning token streaming (`reasoning_content`).

> [!NOTE]
> **Excluded Machine-Specific Extensions**: `herdr-agent-state.ts` is intentionally excluded
> from `setup-pi-agent.js` and portable provisioners because it is a local host-specific state
> extension intended for your primary workstation only.

---

## 📂 Configuration Files Overview

| File Path | Description |
| :--- | :--- |
| [`pi/setup-pi-agent.js`](file:///home/kushal/projects/system-instructions/pi/setup-pi-agent.js) | Main idempotent Node.js provisioner script (Windows/Linux/WSL). |
| [`pi/remove-9router-hook.js`](file:///home/kushal/projects/system-instructions/pi/remove-9router-hook.js) | Removes the legacy always-on hook from older machines. |
| [`~/.pi/.env`](file:///home/kushal/.pi/.env) | Isolated environment variables (web-search, 9Router, agent-browser provider keys — see the managed-keys table above). |
| [`~/.pi/web-search.json`](file:///home/kushal/.pi/web-search.json) | Configures `web_search` provider routing and fallback resolution; each provider key is a `!node` reader into `~/.pi/.env`, so filling `.env` activates the provider. |
| [`~/.pi/config/pi-agent-browser-native/config.json`](file:///home/kushal/.pi/config/pi-agent-browser-native/config.json) | agent-browser user config enabling the `agent_browser_web_search` companion (reads EXA/BRAVE keys from `~/.pi/.env`). |
| [`~/.pi/agent/auth.json`](file:///home/kushal/.pi/agent/auth.json) | Token store for provider API keys. |
| [`~/.pi/agent/settings.json`](file:///home/kushal/.pi/agent/settings.json) | User preferences, theme, and package manifest. |
| [`~/.pi/agent/models.json`](file:///home/kushal/.pi/agent/models.json) | Provider registry for 9Router models (written by `/9router-sync`). |
| [`~/.pi/agent/extensions/9router-sync.ts`](file:///home/kushal/.pi/agent/extensions/9router-sync.ts) | Automatic tool-schema sanitizer + on-demand 9Router model sync extension. |
