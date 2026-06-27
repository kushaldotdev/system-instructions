# System Instructions

AI workflow rules for coding agents. Portable across opencode, Claude Code, Antigravity, Codex, and Cline.

## Quick Start

```bash
# Clone once to a central location
git clone https://github.com/kushaldotdev/system-instructions ~/system-instructions

# Install globally -- applies to ALL projects automatically
bash ~/system-instructions/.agents/install.sh --global

# Or install per project (skips tools already installed globally)
bash ~/system-instructions/.agents/install.sh --project ~/my-project
```

During installation, you choose the **instructions format**:

| Format | Files | Token cost |
|--------|-------|------------|
| **Modular** (default) | `SYSTEM_PROMPT.md` + `RULES.md` | ~590t always + ~1,300t on-demand |
| **Standalone** | `INSTRUCTIONS.md` (merged) | ~2,030t always loaded |

## Structure

```
.agents/
  SYSTEM_PROMPT.md          <- always-loaded rules (role, caveman, phase control, rules,
  |                             context budget, tools/MCP, phase details, subagents, complex tasks)
  RULES.md                  <- loaded on-demand for Plan/Review (plan framework, decision records,
  |                             review heuristics, debugging, self-review, testing, refactoring,
  |                             commit hygiene)
  CHECKPOINT.md.template    <- session checkpoint template (context overflow recovery)
  AGENTS.md.template        <- scaffold for project-specific context
  install.sh                <- Unix installer
  install.bat               <- Windows installer

INSTRUCTIONS.md             <- standalone merge (SYSTEM_PROMPT.md + RULES.md)
```

## How Deployment Works

You keep one central copy of the rules. Every tool gets a small **instruct bridge** file that tells the AI to read the central files using absolute paths. The format (modular or standalone) determines which files the bridge references.

### Global Install

Creates instruct bridges at user-configurable locations. Once done, every project on this machine inherits the rules automatically.

| Tool | File created |
|------|-------------|
| opencode | `~/.config/opencode/opencode.jsonc` |
| Claude Code | `~/.claude/CLAUDE.md` |
| Antigravity | `~/.gemini/GEMINI.md` |
| Codex | `~/.codex/AGENTS.md` |
| Cline | `~/Documents/Cline/Rules/000-system-instructions.md` |
| Kilo Code | `~/.config/kilo/kilo.jsonc` |

### Project Install

Creates bridge files inside a project directory. Tools already configured globally are skipped automatically.

| Tool | File | Method |
|------|------|--------|
| opencode | `opencode.jsonc` | `instructions` array with absolute paths |
| Antigravity | `.agent/rules/SYSTEM_PROMPT.md` + `RULES.md` | Symlinks to central files |
| Claude Code | `CLAUDE.md` | Instruct bridge + preserves project content |
| Codex | `AGENTS.md` | Instruct bridge + preserves project content |
| Cline | `.clinerules` | Instruct bridge + preserves project content |
| Kilo Code | `kilo.jsonc` | `instructions` array with absolute paths |

## How It Works

| File | When loaded | Token cost |
|------|-------------|------------|
| SYSTEM_PROMPT.md | session start | ~590 |
| RULES.md | first Plan or Review action | ~1,300 (one time) |
| CHECKPOINT.md.template | on checkpoint trigger (context overflow) | ~200 (one time per checkpoint) |
| Project AGENTS.md | session start | project-dependent |
| **Total** | | **~1,890 + project context** |

## Checkpoint System

When a session context grows large (~50 turns), after completing changes, or after finding bugs during review -- the AI offers to write a **checkpoint** and resume in a fresh session. This prevents context bloat and memory drift.

**Flow:**
1. AI detects trigger condition and asks: "Context large -- write checkpoint and resume new session? [y/N]"
2. User approves -- AI writes checkpoint to `.agents/state/YYYY-MM-DD-<slug>.md` using the template
3. User starts a fresh session and runs: `Resume from .agents/state/<file>`
4. New AI reads checkpoint + loads RULES.md fresh -- continues exactly where left off

Checkpoints include: goal, current state, files changed, open bugs, key decisions, remaining work, and the exact next step. The template is copied alongside SYSTEM_PROMPT.md at install time.

## LSP Support

The installer prompts whether to enable **LSP (Language Server Protocol)** for opencode.

| Setting | Effect |
|---------|--------|
| LSP enabled | `"lsp": true` added to `opencode.jsonc`. OpenCode auto-detects and starts language servers (TypeScript, Python, HTML, CSS, Go, Rust, etc.) when matching files are opened. Diagnostics are fed back to the agent. |
| LSP disabled (default) | No LSP config. Agent uses grep/read for code navigation. Saves ~small token overhead. |

**Token impact**: LSP adds diagnostic messages to context when reading files. Near-zero for clean codebases. Tens to low hundreds of tokens for error-heavy files.

## Updating Rules

Edit central files, then re-run the installer:

```bash
bash ~/system-instructions/.agents/install.sh --global
bash ~/system-instructions/.agents/install.sh --project ~/my-project
```

Instruct bridges always reference central files by absolute path, so the AI reads the latest content every session. No stale copies.
