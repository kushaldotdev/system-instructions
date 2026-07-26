# System Instructions

AI workflow rules for coding agents. Portable across opencode, Claude Code, Antigravity, Codex, and Cline.

## OpenCode Custom Modes

Portable custom agent configurations for OpenCode in the `opencode/` directory. Supports five specialized modes with per-mode model selection and permissions.

### Configured Modes

| Mode | Purpose | Model | Permissions |
|------|---------|-------|-------------|
| **`plan`** | Read-only planning | `9router-chatgpt/cx/gpt-5.6-sol` | Edit `.md` only, bash ask |
| **`test`** | Test authoring and validation | `9router-opencode-go/ocg/glm-5.2` | Edit + bash allow |
| **`build`** | Code implementation | `9router-opencode-go/ocg/glm-5.2` | Edit allow, bash ask |
| **`review`** | Architectural/security review | `9router-chatgpt/cx/gpt-5.6-sol` | Edit deny, bash ask |
| **`general`** | High-permission exploratory | `9router-antigravity/ag/gemini-3.5-flash-low` | Edit + bash allow |

### Installation

Separate scripts for separate locations. Choose global (all projects) or per-project install.

**Linux / WSL:**
```bash
# Interactive (prompts for mode and project)
bash opencode/install.sh

# Global only
bash opencode/install.sh --global

# Project only
bash opencode/install.sh --project ~/my-project
```

**Windows (PowerShell):**
```powershell
# Interactive
.\opencode\install.ps1

# Global only
.\opencode\install.ps1 -Global

# Project only
.\opencode\install.ps1 -Project C:\projects\my-project
```

**Windows (Command Prompt):**
```bat
opencode\install.bat
```

### What Gets Installed

| Scope | Target | Agent files | Config |
|-------|--------|-------------|--------|
| Global | `~/.config/opencode/` | `instructions.md`, `agents/*.md` | `opencode.jsonc` |
| Project | `<project>/.opencode/` | `instructions.md`, `agents/*.md` | `opencode.jsonc` |

Project install is skipped if a global config already exists (deep-merged: global config applies to all projects).

### Cross-Environment (WSL + Windows)

The Linux script detects WSL and also installs to Windows user profiles under `/mnt/c/Users/`. The PowerShell script detects WSL distros and installs to WSL home directories. Run either script to cover both environments.

## Quick Start (Other Agents)

```bash
# Clone once to a central location
git clone https://github.com/kushaldotdev/system-instructions ~/system-instructions

# Install globally -- applies to ALL projects automatically
bash ~/projects/system-instructions/.agents/install.sh --global

# Or install per project (skips tools already installed globally)
bash ~/projects/system-instructions/.agents/install.sh --project ~/my-project
```

During installation, you choose the **instructions format**:

| Format | Files | Token cost |
|--------|-------|------------|
| **Modular** (default) | `SYSTEM_PROMPT.md` + `RULES.md` | small prompt + on-demand rules |
| **Standalone** | `INSTRUCTIONS.md` (merged) | compact rules always loaded |

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

The installer copies generated instruction files beside each tool config. Re-run it after changing central rules.

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
| Antigravity | `.agent/rules/` prompt + `RULES.md` | Generated prompt plus local rule link/copy |
| Claude Code | `CLAUDE.md` | Instruct bridge + preserves project content |
| Codex | `AGENTS.md` | Instruct bridge + preserves project content |
| Cline | `.clinerules` | Instruct bridge + preserves project content |
| Kilo Code | `kilo.jsonc` | `instructions` array with absolute paths |

## How It Works

| File | When loaded | Token cost |
|------|-------------|------------|
| SYSTEM_PROMPT.md | session start | compact always-loaded rules |
| RULES.md | first Plan or Review action | compact on-demand rules |
| CHECKPOINT.md.template | on checkpoint trigger | one time per checkpoint |
| Project AGENTS.md | session start | project-dependent |
| **Total** | | compact rules + project context |

## Checkpoint System

When a session context grows large (asks at ~50 turns, then reminds every 20 turns thereafter: 70, 90, etc.), after completing changes, or after finding bugs during review -- the AI offers to write a **checkpoint** and resume in a fresh session. This prevents context bloat and memory drift.

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
bash ~/projects/system-instructions/.agents/install.sh --global
bash ~/projects/system-instructions/.agents/install.sh --project ~/my-project
```

Re-run installer after editing central files to refresh installed copies.
