# System Instructions

AI workflow rules and environment provisioning for coding agents. Portable across OpenCode, Claude Code, Antigravity, Codex, Cline, Kilo Code, and Pi Agent.

## Overview

This repository provides two core capabilities:
1. **Agent Instructions & Workflows (`.agents/`, `INSTRUCTIONS.md`)**: Shared prompt contracts, work modes (`Plan`, `Review`, `Implement`), strict engineering rules, and context checkpointing across major AI coding assistants.
2. **Pi Agent Sync & Provisioning (`pi/`)**: Automated cross-platform configuration export, provisioning, and extension management for Pi Agent.

---

## Quick Start: Agent Instructions

### Unix / Linux / macOS

```bash
# Global install (applies to all projects)
bash .agents/install.sh --global

# Project install (bridges into a specific project)
bash .agents/install.sh --project /path/to/project
```

### Windows

```bat
:: Batch launcher
.agents\install.bat --global

:: Or PowerShell directly
pwsh -File .agents\install.ps1 -Global
```

### Instruction Formats

During installation, choose the format that fits your context budget:

| Format | Files Loaded | Token Cost | Behavior |
| :--- | :--- | :--- | :--- |
| **Modular** (Recommended) | `SYSTEM_PROMPT.md` + `RULES.md` | ~600 tokens initial + ~1,100 tokens on-demand | Small base prompt; loads full rules only during Plan/Review |
| **Standalone** | `INSTRUCTIONS.md` | ~1,700 tokens always loaded | Single self-contained file with all rules and templates |

---

## Pi Agent Provisioning (`pi/`)

Cross-platform environment sync and provisioning tool (`pi/pi-config-transfer.py`) for Pi Agent across Windows, Linux, and WSL.

### Export Setup

```bash
python3 pi/pi-config-transfer.py export

# With secrets (auth.json, API keys):
python3 pi/pi-config-transfer.py export --include-secrets
```

### Provision / Import Setup

```bash
python3 pi/pi-config-transfer.py import
```

See [pi/README.md](file:///home/kushal/projects/system-instructions/pi/README.md) for full provisioning steps, package lists, and custom extension details.

---

## Repository Structure

```
system-instructions/
├── .agents/
│   ├── SYSTEM_PROMPT.md          # Always-loaded core prompt (role, style, mode, non-negotiables, delegation)
│   ├── RULES.md                  # On-demand rules (plan framework, review heuristics, debug, engineering)
│   ├── CHECKPOINT.md.template    # Session checkpoint template for context overflow recovery
│   ├── AGENTS.md.template        # Scaffold for project-specific instructions
│   ├── install.sh                # Unix/Linux installer (Bash)
│   ├── install.ps1               # Windows installer (PowerShell)
│   └── install.bat               # Windows batch launcher
├── pi/
│   ├── pi-config-transfer.py     # Cross-platform Pi Agent sync & provisioning CLI
│   └── README.md                 # Pi Agent environment & sync documentation
├── pi-setup-export/              # Snapshot directory for Pi configurations, extensions, and manifests
├── INSTRUCTIONS.md               # Standalone merged instructions (SYSTEM_PROMPT.md + RULES.md)
└── README.md                     # Project overview and quick start guide
```

---

## How Deployment Works

The installer links or bridges central rule files into tool configuration paths. Re-run after updating central rules.

### Global Installation

Creates bridges or configuration entries at user-level configuration directories across all projects on the machine.

| Tool | Config / Bridge Location |
| :--- | :--- |
| **OpenCode** | `~/.config/opencode/opencode.jsonc` |
| **Claude Code** | `~/.claude/CLAUDE.md` |
| **Antigravity** | `~/.gemini/GEMINI.md` |
| **Codex** | `~/.codex/AGENTS.md` |
| **Cline** | `~/Documents/Cline/Rules/000-system-instructions.md` |
| **Kilo Code** | `~/.config/kilo/kilo.jsonc` |

### Project Installation

Creates bridge files inside a specific project directory. Tools configured globally are skipped automatically.

| Tool | Target File | Integration Method |
| :--- | :--- | :--- |
| **OpenCode** | `opencode.jsonc` | `instructions` array with central paths |
| **Antigravity** | `.agent/rules/` prompt + `RULES.md` | Prompt rule link / copy |
| **Claude Code** | `CLAUDE.md` | Instruct bridge (preserves project content) |
| **Codex** | `AGENTS.md` | Instruct bridge (preserves project content) |
| **Cline** | `.clinerules` | Instruct bridge (preserves project content) |
| **Kilo Code** | `kilo.jsonc` | `instructions` array with central paths |

---

## Workflow Systems

### 1. Work Modes & Rules

- **Modes**: `[Plan]`, `[Review]`, `[Implement]` (switch via `/plan`, `/review`, `/do`).
- **Style**: Fragment-preferred, verb-first, findings-first, zero conversational filler.
- **Verification**: Strict pre-presentation verification, reproduction, edge case testing, no unverified claims.

### 2. Checkpoint System

When context grows large (~50 turns, then reminded every 20 turns thereafter: 70, 90, etc.), after completed implementations, or after discovering review issues:

1. AI prompts: `Context large -- write checkpoint and resume new session? [y/N]`
2. On approval, state is saved to `.agents/state/YYYY-MM-DD-HH-MM-SS-<slug>.md`.
3. In a fresh session: `Resume from .agents/state/<file>`.

### 3. OpenCode LSP Integration

Installer configures optional Language Server Protocol (`"lsp": true/false`) in `opencode.jsonc` for symbol resolution and diagnostics.

