# Pi Agent Environment & Sync Guide

Automated provisioning and configuration sync for Pi Agent.
Works on **Windows, Linux, and WSL**.

Replaces the old `setup-pi-agent.js` provisioner with a single Python tool that
**exports** your complete Pi setup from your main machine and **provisions** a new
machine with the exact same extensions, packages, configs, and disabled-states —
without copying API keys or auth tokens.

---

## 🚀 Quick Start

### On your main machine — export your setup

```bash
python3 pi-config-transfer.py export            # -> ./pi-setup-export/ (in cwd)
```

This creates a small, portable snapshot containing:
- **Config only** — no `npm/` node_modules tree, no sessions, no auth
- Your **package list** (14 packages) → reinstalled on the target via `pi install`
- Your **custom extensions** (web-search-trim, pi-update, subagent, pi-rtk-optimizer, ...)
- **settings.json** wholesale — disabled-extension filters preserved
- The **pi-web-access trim patch** (provider trim applied automatically on import)
- `models.json`, `web-search.json` (keys **stripped**), agent-browser config,
  AGENTS.md, themes, skills, prompts, chains, profiles

### On the new machine — provision in one command

```bash
python3 pi-config-transfer.py import
```

That's it. Import looks for `./pi-setup-export/` by default (the same default folder
that `export` creates), so you only need to pass a folder name if you renamed the
export. It does everything, in order:

| Step | What it does |
| :--- | :--- |
| **1. pi itself** | If `pi` not on PATH → `npm install -g @earendil-works/pi-coding-agent` |
| **2. Config files** | Restores extensions/, settings.json, models.json, web-search.json, config/, AGENTS.md, themes, skills, prompts, chains, profiles (backs up existing files first) |
| **3. Packages** | `pi install` each package from the exported list (idempotent, keeps disabled-extension filters) |
| **4. Trim patch** | Applies the pi-web-access provider trim (`openai`, `exa`, `tavily`) |
| **5. Binaries** | Installs `rtk`, `agent-browser` CLI + Chrome for Testing, warns if `ffmpeg` missing |
| **6. Final notes** | Auth/keys reminders, `/reload` |

> [!NOTE]
> **API keys & auth are NOT copied by default.** Re-export with `--include-secrets`
> if you want them, and treat that export like a private key.

---

## 📋 Commands

| Command | Purpose |
| :--- | :--- |
| `python3 pi-config-transfer.py export [dest]` | Create export folder (default `./pi-setup-export/`) |
| `python3 pi-config-transfer.py export --include-secrets` | Also export API keys (models.json apiKey, tavily key) |
| `python3 pi-config-transfer.py export --dry-run` | Preview what would be exported |
| `python3 pi-config-transfer.py import [src]` | **Full provisioning** (6 steps above); defaults to `./pi-setup-export/` |
| `python3 pi-config-transfer.py import [src] --no-install` | Config files only — skip pi/packages/binaries/patch |
| `python3 pi-config-transfer.py import [src] --dry-run` | Preview what would be applied |
| `python3 pi-config-transfer.py list [src]` | Show packages + items inside an export; defaults to `./pi-setup-export/` |
| `python3 pi-config-transfer.py check` | Show environment info (platform, paths, tool availability) |

---

## 🔒 Security Model

| Item | Default behavior |
| :--- | :--- |
| `auth.json` (Codex/OpenAI OAuth tokens) | **Never exported** — re-login per machine (`pi auth login`) |
| `tavilyApiKey` (web-search.json) | **Stripped** → `***REDACTED***` unless `--include-secrets` |
| `models.json` `apiKey` (custom provider keys) | **Stripped** → `***REDACTED***` unless `--include-secrets` |
| `npm/`, `bin/`, `git/`, `sessions/`, `missions/` | **Never exported** — packages reinstalled from the list |
| Export folder (with `--include-secrets`) | Treat like a private key — contains real credentials |

A best-effort **secret scan** warns if an exported file contains a key-shaped value.

---

## 📦 Installed Packages & Extensions

### Standard Packages (`settings.json`)

| Package Name | Purpose / Functionality |
| :--- | :--- |
| **`pi-mcp-adapter`** | Integrates Model Context Protocol (MCP) servers and tools into Pi. |
| **`pi-web-access`** | Web search, webpage scraping, YouTube transcripts, PDF reading, multi-provider fallback (trimmed to openai/exa/tavily). |
| **`pi-subagents`** | Spawn, communicate with, and orchestrate sub-agents. |
| **`pi-lens`** | LSP diagnostics, read-guard file enforcement, inline code checks. |
| **`@juicesharp/rpiv-ask-user-question`** | Interactive multi-choice question prompts. |
| **`@ff-labs/pi-fff`** | Fast File Finder (FFF) with frecency ranking. |
| **`@juicesharp/rpiv-todo`** | Persistent session task list. |
| **`pi-agent-browser-native`** | Headless browser automation and web interaction. |
| **`pi-rtk-optimizer`** | RTK command rewriting + tool output compaction (needs the `rtk` binary — auto-installed by import). |
| **`opencode-pi`** | OpenCode provider integration. |

Plus (from the exported `settings.json`): `cc-safety-net`, `pi-token-speed`,
`pine-of-glass`, `pi-antigravity-rotator`.

### External binaries handled by import

| Binary | Needed by | Import behavior |
| :--- | :--- | :--- |
| `rtk` (`~/.local/bin/rtk`) | `pi-rtk-optimizer` | ✅ Auto-installs if missing (official installer) |
| `agent-browser` (npm global) | `pi-agent-browser-native` | ✅ `npm install -g agent-browser` if missing |
| Chrome for Testing (`~/.agent-browser/browsers/`) | `agent_browser` tool launch | ✅ `agent-browser install` (one-time download) |
| `ffmpeg` | browser screen recording (`record stop`) | ⚠️ Warning only (apt/brew/winget) |

---

## 🛠️ Custom Local Extensions

| Extension | What it does |
| :--- | :--- |
| `web-search-trim` | `/web-search-trim` — trims web_search providers to openai/exa/tavily (re-patches pi-web-access after updates) |
| `pi-update` | `/update` — updates pi + all extensions with live progress + completion message |
| `subagent` | Compact tool descriptions, summary inline display, async-by-default |
| `pi-rtk-optimizer` | RTK output compaction configuration |

These live under `~/.pi/agent/extensions/` and are **exported wholesale** — new
extensions added later are picked up automatically on the next export (no code change).

---

## 📂 Configuration Files Overview

| File Path | Description |
| :--- | :--- |
| [`pi/pi-config-transfer.py`](file:///home/kushal/projects/system-instructions/pi/pi-config-transfer.py) | The export/import/provision tool (Python 3, cross-platform). |
| [`~/.pi/agent/settings.json`](file:///home/kushal/.pi/agent/settings.json) | User preferences, theme, package manifest (incl. disabled-extension filters). |
| [`~/.pi/agent/extensions/`](file:///home/kushal/.pi/agent/extensions/) | Custom slash-command extensions (web-search-trim, pi-update, subagent, ...). |
| [`~/.pi/agent/models.json`](file:///home/kushal/.pi/agent/models.json) | Custom provider definitions (apiKey stripped on export). |
| [`~/.pi/web-search.json`](file:///home/kushal/.pi/web-search.json) | web_search provider routing + fallback config (key stripped on export). |
| [`~/.pi/config/pi-agent-browser-native/config.json`](file:///home/kushal/.pi/config/pi-agent-browser-native/config.json) | agent-browser user config. |
| [`~/.pi/agent/auth.json`](file:///home/kushal/.pi/agent/auth.json) | Token store for provider logins (never exported). |

---

## 🔑 After Import (on the new machine)

1. **Re-add keys** if you didn't use `--include-secrets`:
   - `~/.pi/web-search.json` → `tavilyApiKey`
   - `~/.pi/agent/models.json` → custom provider `apiKey`
2. **Log in** for model access: run `pi` → `/auth` (or `pi auth login`).
3. **`/reload`** inside pi to load the imported extensions.

---

## 🧹 Post-Migration Cleanup

- Export folders (`pi-setup-export/`) are git-ignored — they can contain machine
  state and are meant to travel by USB/scp, not be committed.
- `.pi-transfer.bak` backups of overwritten files are kept next to the originals.
- Backup files that contain secrets (e.g. `web-search.json.pi-transfer.bak`) should
  be `chmod 600`.
