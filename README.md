# System Instructions

AI workflow rules for coding agents. Portable across opencode, Claude Code, Antigravity, Codex, and Cline.

## OpenCode Custom Modes

Portable custom agent configurations for OpenCode in the `opencode/` directory.
Includes six specialized agents, automatic risk-based review routing, and a
shared exhaustive-review skill.

### Configured Modes

| Mode | Purpose | Permissions |
| ------ | --------- | ------------- |
| **`plan`** | Read-only planning | Edit `.md` only, bash allow |
| **`test`** | Test authoring and validation | Edit + bash allow |
| **`build`** | Code implementation | Edit allow, bash allow |
| **`review`** | Architectural/security review | Write `.agents/review/**`; shell allowed for read-only verification |
| **`audit`** | Direct or delegated deep-review specialist | Write `.agents/review/**`; shell allowed for read-only verification |
| **`general`** | High-permission exploratory | Edit + bash allow |

### Installation

Run the same dependency-free Python 3.10+ installer from Windows or WSL. Choose
the current environment, the other environment, or both. Cross-environment
installation delegates to the target environment's own Python so home paths,
locking, config paths, and OpenCode validation remain native.

**Linux / WSL:**

```bash
# Interactive (prompts for mode and project)
python3 opencode/install.py

# Choose WSL, Windows, or both environments
python3 opencode/install.py --environment current --global
python3 opencode/install.py --environment windows --global
python3 opencode/install.py --environment both --global

# Global only
python3 opencode/install.py --global

# Project only
python3 opencode/install.py --project ~/my-project

# Global and current project
python3 opencode/install.py --both

# Preserve current LSP setting (default), or set it explicitly
python3 opencode/install.py --global --lsp
python3 opencode/install.py --global --no-lsp
```

**Windows:**

```bat
# Interactive
py -3 opencode\install.py

# Choose Windows, WSL, or both environments
py -3 opencode\install.py --environment current --global
py -3 opencode\install.py --environment wsl --global
py -3 opencode\install.py --environment both --global

# Select a non-default WSL distribution
py -3 opencode\install.py --environment wsl --wsl-distro Ubuntu-24.04 --global

# Global only
py -3 opencode\install.py --global

# Project only
py -3 opencode\install.py --project C:\projects\my-project

# Global and current project
py -3 opencode\install.py --both
```

Environment selection is independent from install scope:

| Option | Meaning |
| --- | --- |
| `--environment current` | Install only where `install.py` is running |
| `--environment windows` | Install in Windows; available from Windows or WSL |
| `--environment wsl` | Install in WSL; available from WSL or Windows |
| `--environment both` | Install in both Windows and WSL |
| `--global` | Install globally in each selected environment |
| `--project <path>` | Install for the project, converting the caller-native path for the other environment |
| `--both` | Install global plus project scope; unrelated to `--environment both` |

Cross-target prerequisites:

- WSL to Windows: Windows Python 3.10+ installed under the current user's
  `%LOCALAPPDATA%` (the standard WindowsApps `py.exe`, Python launcher, or
  Python install layout), plus normal WSL interoperability and
  `/usr/bin/wslpath`. WSL normally provides that path as a trusted symlink to
  its root-owned `/init` runtime; the installer accepts that standard layout.
- Windows to WSL: `wsl.exe` and Python 3.10+ in the selected/default WSL
  distribution.
- `--wsl-distro <name>` selects a distribution; otherwise the Windows default
  WSL distribution is resolved once and pinned for conversion and execution.
- Enter `--project` in the launching environment's native path format. The
  installer converts it before delegation.

Without `--environment`, interactive Windows/WSL runs prompt for current,
other, or both. Non-interactive runs default to `current`. Native Linux supports
only `current`.

### What Gets Installed

| Scope | Target | Installed workflow | Config |
| :--- | :--- | :--- | :--- |
| Global | `~/.config/opencode/` | `instructions.md`, six `agents/*.md`, `skills/exhaustive-review/SKILL.md` | Existing `opencode.json(c)` or new `opencode.jsonc` |
| Project | `<project>/.opencode/` | `instructions.md`, six `agents/*.md`, `skills/exhaustive-review/SKILL.md` | Existing `opencode.json(c)` or new `opencode.jsonc` |

Project installation is never skipped merely because global configuration
exists. Installer safely merges managed agents and instruction path while
preserving the semantics of unrelated settings, custom agents, plugins, and
current LSP configuration. JSONC comments/formatting may be normalized; the
timestamped pre-change backup retains original bytes. Repeated installation is
idempotent.

Each scope and environment is an independent idempotent install. A completed
target remains installed if a later target fails; fix the reported prerequisite
or validation error and rerun to reconcile the remaining target. Transport
failure after remote execution can make remote completion ambiguous, but rerun
is safe. Atomic replacement protects individual files; the installer does not
claim one all-or-nothing transaction across multiple files, scopes, or operating
environments. A hard process kill can therefore require a rerun.

Installer validates resolved config, skill discovery, and both review agents
with `opencode debug` when OpenCode is available. Quit and restart OpenCode after
installation because configuration-time files are not hot-reloaded.

One implementation handles JSONC parsing, semantic config merge, backups,
cooperative shared-target locking, atomic replacement, per-target rollback,
hash-verified isolated cross-environment delegation, and side-effect-controlled
runtime discovery on both Windows and WSL. No Node package,
PowerShell script, shell installer, or third-party Python package is required.

### Review Workflow

- Local, one-layer, reversible changes receive one exhaustive review.
- Cross-layer, distributed, destructive, security, financial, migration,
  datetime, scheduling, public-contract, or otherwise high-risk changes receive
  independent specialist audits followed by synthesis.
- All specialist reports finish before synthesis. Synthesis freezes one
  canonical finding set before fixes begin.
- Explicit overrides: `single review`, `deep review`, `multiple reviewers`, or
  `skip review`. An explicit skip ends as `Review skipped — not workflow
  complete`, not a pass.
- Shared methodology lives in
  `opencode/skills/exhaustive-review/SKILL.md`.

Review findings are written under each project's
`.agents/review/YYYY-MM-DD-HH-MM-SS-<slug>.md`, using environment-local
24-hour time. Reports are human-readable Markdown with
an executive summary, plainly explained findings, remediation guidance,
coverage, verification, residual risks, and verdict. Canonical pipe-delimited
finding lines remain embedded for stable search and tooling.
Review/audit agents use native clock commands to obtain this timestamp and may
run read-only verification commands. Existing same-second paths are never
overwritten; a numeric suffix is added instead.

Compact manual evaluation scenarios live in
`opencode/evaluation/exhaustive-review-scenarios.md`.

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
| ------ | ------------- |
| opencode | `~/.config/opencode/opencode.jsonc` |
| Claude Code | `~/.claude/CLAUDE.md` |
| Antigravity | `~/.gemini/GEMINI.md` |
| Codex | `~/.codex/AGENTS.md` |
| Cline | `~/Documents/Cline/Rules/000-system-instructions.md` |
| Kilo Code | `~/.config/kilo/kilo.jsonc` |

### Project Install

Creates bridge files inside a project directory. Tools already configured globally are skipped automatically.

| Tool | File | Method |
| ------ | ------ | -------- |
| opencode | `opencode.jsonc` | `instructions` array with absolute paths |
| Antigravity | `.agent/rules/` prompt + `RULES.md` | Generated prompt plus local rule link/copy |
| Claude Code | `CLAUDE.md` | Instruct bridge + preserves project content |
| Codex | `AGENTS.md` | Instruct bridge + preserves project content |
| Cline | `.clinerules` | Instruct bridge + preserves project content |
| Kilo Code | `kilo.jsonc` | `instructions` array with absolute paths |

## How It Works

| File | When loaded | Token cost |
| ------ | ------------- | ------------ |
| SYSTEM_PROMPT.md | session start | compact always-loaded rules |
| RULES.md | first Plan or Review action | compact on-demand rules |
| CHECKPOINT.md.template | on checkpoint trigger | one time per checkpoint |
| Project AGENTS.md | session start | project-dependent |
| **Total** | | compact rules + project context |

## Checkpoint System

When a session context grows large (asks at ~50 turns, then reminds every 20 turns thereafter: 70, 90, etc.), after completing changes, or after finding bugs during review -- the AI offers to write a **checkpoint** and resume in a fresh session. This prevents context bloat and memory drift.

**Flow:**

1. AI detects trigger condition and asks: "Context large -- write checkpoint and resume new session? [y/N]"
2. User approves -- AI writes checkpoint to `.agents/state/YYYY-MM-DD-HH-MM-SS-<slug>.md` using the template
3. User starts a fresh session and runs: `Resume from .agents/state/<file>`
4. New AI reads checkpoint + loads RULES.md fresh -- continues exactly where left off

Checkpoints include: goal, current state, files changed, open bugs, key decisions, remaining work, and the exact next step. The template is copied alongside SYSTEM_PROMPT.md at install time.

## LSP Support

The installer prompts whether to enable **LSP (Language Server Protocol)** for opencode.

| Setting | Effect |
| --------- | -------- |
| LSP enabled | `"lsp": true` added to `opencode.jsonc`. OpenCode auto-detects and starts language servers (TypeScript, Python, HTML, CSS, Go, Rust, etc.) when matching files are opened. Diagnostics are fed back to the agent. |
| Preserve (default) | Existing `lsp` value is left unchanged; a new config receives no `lsp` key. |
| LSP disabled | `"lsp": false` is written explicitly. Agent uses other configured navigation tools. |

**Token impact**: LSP adds diagnostic messages to context when reading files. Near-zero for clean codebases. Tens to low hundreds of tokens for error-heavy files.

## Updating Rules

Edit central files, then re-run the installer:

```bash
bash ~/projects/system-instructions/.agents/install.sh --global
bash ~/projects/system-instructions/.agents/install.sh --project ~/my-project
```

Re-run installer after editing central files to refresh installed copies.
