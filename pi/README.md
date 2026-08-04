# Pi Agent Harness Environment & Setup Guide

Automated provisioning, dynamic model discovery, and extension catalog for Pi Agent.

---

## 🚀 Quick Start (New Computer Setup)

To setup or restore Pi Agent settings, extensions, and configurations on a new machine:

```bash
node setup-pi-agent.js
```

### Manual Package Installation Commands

Alternatively, to install packages manually via `pi` CLI:

```bash
pi install npm:pi-mcp-adapter
pi install npm:pi-web-access
pi install npm:pi-subagents
pi install npm:pi-lens
pi install npm:@juicesharp/rpiv-ask-user-question
pi install npm:@ff-labs/pi-fff
pi install npm:@juicesharp/rpiv-todo
pi install npm:pi-agent-browser-native
pi install npm:pi-rtk-optimizer
```

> [!NOTE]
> The setup script is **idempotent and safe to run multiple times**. It merges missing configuration keys and packages without overwriting your existing API tokens or creating duplicate entries.


---

## 🔑 Post-Installation Credentials Setup

After running `node setup-pi-agent.js`, populate your API keys in the generated environment files:

### 1. `~/.pi/.env`
```env
TAVILY_API_KEY="tvly-your-key-here"
NINE_ROUTER="sk-your-9router-key-here"
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
| **`pi-rtk-optimizer`** | Real-time token window optimizer and context window usage manager. |

---

## 🛠️ Custom Local Extensions

### `9router-discovery.ts` (`~/.pi/agent/extensions/9router-discovery.ts`)

- **Dynamic Model Discovery**: On `session_start`, queries `NINE_ROUTER_BASE_URL` (`/v1/models`) and populates `~/.pi/agent/models.json` with 30+ 9Router models automatically.
- **TypeBox Schema Sanitizer**: Intercepts tool parameters on `session_start` and `before_agent_start`, stripping internal TypeBox metadata keys (`~optional`, `~kind`, `~readonly`) to prevent `HTTP 400: Unknown name "~optional"` errors when calling Gemini / Antigravity endpoints.
- **Reasoning Token Support**: Configures provider compatibility options allowing live reasoning token streaming (`reasoning_content`).

> [!NOTE]
> **Excluded Machine-Specific Extensions**: `herdr-agent-state.ts` is intentionally excluded from `setup-pi-agent.js` and portable provisioners because it is a local host-specific state extension intended for your primary workstation only.


---

## 📂 Configuration Files Overview

| File Path | Description |
| :--- | :--- |
| [`/home/kushal/projects/test/setup-pi-agent.js`](file:///home/kushal/projects/test/setup-pi-agent.js) | Main idempotent Node.js provisioner script. |
| [`~/.pi/.env`](file:///home/kushal/.pi/.env) | Isolated environment variables (`TAVILY_API_KEY`, `NINE_ROUTER`). |
| [`~/.pi/web-search.json`](file:///home/kushal/.pi/web-search.json) | Configures `web_search` provider routing and fallback resolution. |
| [`~/.pi/agent/auth.json`](file:///home/kushal/.pi/agent/auth.json) | Token store for provider API keys. |
| [`~/.pi/agent/settings.json`](file:///home/kushal/.pi/agent/settings.json) | User preferences, theme, and package manifest. |
| [`~/.pi/agent/models.json`](file:///home/kushal/.pi/agent/models.json) | Auto-generated provider registry for 9Router models. |
| [`~/.pi/agent/extensions/9router-discovery.ts`](file:///home/kushal/.pi/agent/extensions/9router-discovery.ts) | Dynamic model discovery and TypeBox schema sanitizer extension code. |
