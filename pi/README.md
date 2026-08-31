# Pi Coding Agent Configuration & Extensions

This directory contains the configurations, custom extensions, and setup utilities for the **Pi Coding Agent**, mirrored from `\\wsl.localhost\Ubuntu-24.04\home\kushal\.pi\agent\`.

---

## 1. Custom Extensions & Configurations in `pi/agent/extensions/`

These local extensions and configuration overrides customize Pi's behavior, safety guardrails, background execution, and search optimizations.

| Directory / File | Description | Approx. Context Tokens |
| :--- | :--- | :--- |
| `agent/extensions/command-guard/index.ts` | Cross-platform safety guard intercepting destructive shell commands (`rm`, `git reset`, `docker prune`, etc.), sensitive file writes/edits, and secret credential reads with interactive allow/block prompts and `/guard:yolo` support. | `0 tokens` (event hooks & UI prompts only) |
| `agent/extensions/pi-update/index.ts` | In-session update manager providing `/update` (`/update pi`, `/update ext`) with live streaming progress and detailed diff summaries of updated packages. | `0 tokens` (slash command only) |
| `agent/extensions/pi-web-subagent-bridge/index.ts` | Background bridge that converts and synchronizes `pi-subagents` task sessions into the JSONL DAG tree format expected by the `@agegr/pi-web` UI. | `0 tokens` (background sync only) |
| `agent/extensions/subagent/config.json` | Configuration for subagent execution defining `fresh` context, compact tool displays, default asynchronous execution (`asyncByDefault: true`), and output artifact paths. | `0 tokens` (config only) |
| `agent/extensions/web-search-trim/config.json` | Configuration defining the active search provider whitelist (keeping `openai`, `exa`, `tavily`). | `0 tokens` (config only) |
| `agent/extensions/web-search-trim/index.ts` | Extension and `/web-search-trim` slash command to patch `pi-web-access` source schemas in-place, trimming the 20+ search provider list down to active providers to conserve prompt tokens. | `-150 to -250 tokens` (net token reduction in tool schema) |

---

## 2. Currently Installed Extensions & Packages

Packages currently active and configured in `~/.pi/agent/settings.json`:

| Package | Install Command | Description (Single Sentence) | Approx. Context Tokens (When Active) |
| :--- | :--- | :--- | :--- |
| `@ff-labs/pi-fff` | `pi install npm:@ff-labs/pi-fff` | Adds ultra-fast, FFF-powered fuzzy file and content search capabilities. | `~120 tokens` (`fff` tool schema) |
| `pi-rtk-optimizer` | `pi install npm:pi-rtk-optimizer` | Optimizes shell commands and compacts tool output using RTK rewriting rules. | `~60 tokens` (concise guideline injection) |
| `pi-token-speed` | `pi install npm:pi-token-speed` | Measures and displays real-time tokens-per-second generation metrics. | `0 tokens` (client UI metrics only) |
| `pine-of-glass` | `pi install npm:pine-of-glass` | Provides observability, inspection, and telemetry extensions for Pi sessions. | `0 tokens` (observability & cache stats) |
| `pi-antigravity` | `pi install npm:pi-antigravity` | Connects Pi to Google Antigravity / Cloud Code Assist models and capabilities. | `0 tokens` (model provider adapter) |
| `@pi-vault/pi-dcp` | `pi install npm:@pi-vault/pi-dcp` | Performs dynamic context pruning and incremental tool output compression to maximize context efficiency. | `~80 tokens` (compression tool overhead; saves thousands in session history) |
| `@dietrichgebert/ponytail` | `pi install npm:@dietrichgebert/ponytail` | Enforces a senior developer review persona focused on simplifying solutions and eliminating unnecessary code. | `~150 - 300 tokens` (system prompt instructions when review mode enabled) |
| `pi-cockpit` | `pi install npm:pi-cockpit` | Adds a responsive operational status sidebar, fallback widgets, and footer UI for Pi. | `0 tokens` (TUI sidebar / footer renderers only) |
| `@narumitw/pi-btw` | `pi install npm:@narumitw/pi-btw` | Adds a `/btw` command to ask side questions in an isolated sub-context without polluting main history. | `0 tokens` (slash command only) |
| `@narumitw/pi-lsp` | `pi install npm:@narumitw/pi-lsp` | Exposes configurable, language-agnostic LSP diagnostics and quick-fix tools through a shared runner. | `~150 tokens` (`lsp_diagnostics` & `lsp_fix` tool schemas) |
| `@juicesharp/rpiv-todo` | `pi install npm:@juicesharp/rpiv-todo` | Adds a persistent, live overlay todo list for tracking multi-step agent tasks across conversation compactions. | `~140 tokens` (`todo` tool schema) |
| `pi-subagents` | `pi install npm:pi-subagents` | Enables single-agent delegation, specialized role personas, and scripted multi-agent workflows (Claude Code-style profiles take more tokens). | `~7,000 tokens` (with full agent prompts & Claude Code-style profiles) |
| `pi-web-search` | `pi install npm:pi-web-search` | Lightweight, provider-native web search across Gemini, OpenAI, and Anthropic with Gemini URL context. | `~0.1k tokens` (~100 tokens; compact schema) |
| `pi-hashline-edit-pro` | `pi install npm:pi-hashline-edit-pro` | Provides hash-anchored read/replace/grep editing tools with persistent undo to prevent stale line diff mismatches. | `~1.6k tokens` (anchor tool schemas) |

---

## 3. Other Extensions & Packages (Reference & Alternatives)

List of other relevant packages, previously installed extensions, or alternatives and their context footprints:

| Package | Install Command | Description (Single Sentence) | Approx. Context Tokens (When Active) |
| :--- | :--- | :--- | :--- |
| `@juicesharp/rpiv-web-tools` | `pi install npm:@juicesharp/rpiv-web-tools` | Comprehensive web toolkit providing web search, URL fetching, content parsing, and extraction tools. | `~0.7k tokens` (~700 tokens) |
| `pi-web-access` | `pi install npm:pi-web-access` | Adds multi-provider web search, URL scraping, GitHub repository cloning, and media content analysis. | `~300 - 600 tokens` (`web_search`, `source_check`, `fetch_content`; trimmed to ~250) |
| `pi-mcp-adapter` | `pi install npm:pi-mcp-adapter` | Integrates Model Context Protocol (MCP) servers and tools directly into Pi. | `~350 - 500+ tokens` (base MCP adapter tools + schema per active MCP tool) |
| `pi-lens` | `pi install npm:pi-lens` | Provides real-time code intelligence, language server (LSP) diagnostics, formatters, and AST structural queries. | `~200 tokens` (LSP / AST tool definitions) |
| `pi-agent-browser-native` | `pi install npm:pi-agent-browser-native` | Exposes `agent-browser` as a native tool for web browser automation and interaction. | `~250 - 350 tokens` (`agent_browser` tool schema + prompt rules) |

---

## 4. Installed Skills

Summary of available custom skills in `~/.pi/agent/skills/` and approximate token overhead when activated in context:

| Skill | Description (Single Sentence) | Approx. Tokens When Loaded |
| :--- | :--- | :--- |
| `codebase-design` | Establishes a shared design vocabulary for deep modules, interface boundaries, and AI-navigable architecture. | `~1,200 tokens` |
| `domain-modeling` | Guides building, refining, and recording ubiquitous terminology and Architectural Decision Records (ADRs). | `~850 tokens` |
| `grilling` | Relentlessly stress-tests and interviews the user on design plans, trade-offs, and technical assumptions. | `~600 tokens` |
| `handoff` | Condenses and structures the current conversation into a comprehensive handoff artifact for a new agent. | `~500 tokens` |
| `improve-codebase-architecture` | Scans codebases for architectural friction and deepening opportunities, presenting them in visual reports. | `~1,400 tokens` |
