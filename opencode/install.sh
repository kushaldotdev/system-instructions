#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# === Args ===
MODE=""
PROJECT_DIR=""
NO_PAUSE=false
LSP_ENABLED=false
NO_PROMPT=false
while [ $# -gt 0 ]; do
  case "$1" in
    --global) MODE="global"; shift ;;
    --project) MODE="project"; shift; PROJECT_DIR="${1:-}"; [ -z "$PROJECT_DIR" ] && { echo "Usage: --project <dir>"; exit 1; }; shift ;;
    --no-pause) NO_PAUSE=true; shift ;;
    --lsp) LSP_ENABLED=true; shift ;;
    --no-prompt) NO_PROMPT=true; shift ;;
    --help|-h) echo "Usage: bash install.sh [--global|--project <dir>] [--lsp] [--no-pause] [--no-prompt]"; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

echo "============================================"
echo "  opencode Custom Modes Installer"
echo "============================================"
echo ""

# === Interactive mode ===
if [ -z "$MODE" ]; then
  echo "Install mode (default: global):"
  echo "  g) Global -- applies to ALL projects on this machine"
  echo "  p) Project -- installs in a specific project"
  echo "  b) Both"
  echo "  q) Quit"
  read -p "Choice (g/p/b/q) [default: g]: " mc
  case "$mc" in ""|g|G) MODE="global" ;; p|P) MODE="project" ;; b|B) MODE="both" ;; q|Q) exit 0 ;; *) echo "Invalid"; exit 1 ;; esac
fi

# === LSP for opencode (only if interactive and not already set by arg) ===
if [ "$NO_PROMPT" != true ] && [ -t 0 ] && [ "$LSP_ENABLED" = false ]; then
  echo ""
  echo "Enable LSP for opencode? (Y/n):"
  echo "  LSP provides diagnostics and symbol intelligence when reading files."
  echo "  Note: adds small token overhead (diagnostic messages per file)."
  read -p "Choice (Y/n) [default: Y]: " lsp_choice
  case "$lsp_choice" in
    n|N|no|No) LSP_ENABLED=false ;;
    *) LSP_ENABLED=true ;;
  esac
fi

# === Project dir ===
if [ "$MODE" = "project" ] || [ "$MODE" = "both" ]; then
  if [ -z "$PROJECT_DIR" ]; then
    read -p "Project directory (or Enter for current): " PROJECT_DIR
    PROJECT_DIR="${PROJECT_DIR:-$PWD}"
  fi
  PROJECT_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd)" || { echo "Invalid: $PROJECT_DIR"; exit 1; }
  echo "Project: $PROJECT_DIR"
  echo ""
fi

# === Helpers ===
is_globally_installed() {
  [ -f "$HOME/.config/opencode/opencode.jsonc" ] || [ -f "$HOME/.config/opencode/opencode.json" ]
}

install_to() {
  local target="$1"
  local label="$2"

  echo ""
  echo "  -- opencode custom modes ($label)"
  echo "     target: $target"

  mkdir -p "$target/agents"

  cp -f "$SCRIPT_DIR/instructions.md" "$target/instructions.md"
  cp -f "$SCRIPT_DIR/agents/"*.md "$target/agents/"
  echo "    [copy]   instructions.md, agents/{plan,test,build,review,general}.md"

  local config="$target/opencode.jsonc"
  local inst_path="$target/instructions.md"

  export OP_TARGET="$target"
  export OP_INST_PATH="$inst_path"
  export OP_CONFIG="$config"
  export OP_SCRIPT_DIR="$SCRIPT_DIR"
  export OP_LSP_ENABLED="$LSP_ENABLED"
  python3 << 'PYEOF'
import json, re, os

target = os.environ['OP_TARGET']
inst_path = os.environ['OP_INST_PATH']
config_path = os.environ['OP_CONFIG']
script_dir = os.environ['OP_SCRIPT_DIR']
lsp_enabled = os.environ.get('OP_LSP_ENABLED', 'false').lower() == 'true'

agents_json_path = os.path.join(script_dir, 'agents.json')
with open(agents_json_path, 'r') as f:
    agents_raw = f.read().strip()

first_brace = -1
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        raw = f.read()
    first_brace = raw.find('{')

if first_brace >= 0:
    content = raw
    changed = False

    # 1. Update instructions
    if inst_path not in content:
        match = re.search(r'"instructions"\s*:\s*\[', content)
        if match:
            pos = match.end()
            content = content[:pos] + f'\n    "{inst_path}",' + content[pos:]
            changed = True
        else:
            pos = first_brace + 1
            content = content[:pos] + f'\n  "instructions": [\n    "{inst_path}"\n  ],' + content[pos:]
            changed = True

    # 2. Update lsp
    if lsp_enabled:
        match = re.search(r'"lsp"\s*:\s*(true|false)', content)
        if match:
            content = content[:match.start()] + '"lsp": true' + content[match.end():]
            changed = True
        else:
            pos = first_brace + 1
            content = content[:pos] + '\n  "lsp": true,' + content[pos:]
            changed = True
    else:
        match = re.search(r'"lsp"\s*:\s*(true|false),?\s*', content)
        if match:
            content = content[:match.start()] + content[match.end():]
            changed = True

    # 3. Update agent
    match = re.search(r'"agent"\s*:\s*\{', content)
    if match:
        brace_start = content.find('{', match.start())
        depth = 0
        brace_end = -1
        for i in range(brace_start, len(content)):
            c = content[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    brace_end = i
                    break
        if brace_end > 0:
            new_agent_block = f'"agent": {agents_raw}'
            content = content[:match.start()] + new_agent_block + content[brace_end + 1:]
            changed = True
    else:
        pos = first_brace + 1
        content = content[:pos] + f'\n  "agent": {agents_raw},' + content[pos:]
        changed = True

    if changed:
        with open(config_path, 'w') as f:
            f.write(content)
        print(f'    [update] {config_path}')
    else:
        print(f'    [skip]   {config_path} (no changes needed)')
else:
    new_json = [
        '{',
        '  "$schema": "https://opencode.ai/config.json",',
        '  "instructions": [',
        f'    "{inst_path}"',
        '  ],'
    ]
    if lsp_enabled:
        new_json.append('  "lsp": true,')
    new_json.append(f'  "agent": {agents_raw}')
    new_json.append('}')
    with open(config_path, 'w') as f:
        f.write('\n'.join(new_json))
    print(f'    [create] {config_path}')
PYEOF
}

# === Global install ===
global_install() {
  install_to "$HOME/.config/opencode" "global"

  # WSL: also install to Windows user profiles under /mnt/c/Users/
  if [ -n "${WSL_DISTRO_NAME:-}" ]; then
    for d in /mnt/c/Users/*; do
      if [ -d "$d" ]; then
        base="$(basename "$d")"
        case "$base" in Default|Public|"All Users"|"Default User"|desktop.ini) continue ;; esac
        local win_target="$d/.config/opencode"
        if [ -d "$(dirname "$win_target")" ]; then
          install_to "$win_target" "WSL->Windows ($base)"
        fi
      fi
    done
  fi
}

# === Project install ===
project_install() {
  local target="$1"

  if is_globally_installed; then
    echo "  -- opencode custom modes (project) -- SKIPPED (global already installed)"
    return
  fi

  local opencode_dir="$target/.opencode"
  install_to "$opencode_dir" "project"
}

# === Execute ===
if [ "$MODE" = "global" ] || [ "$MODE" = "both" ]; then
  global_install
fi
if [ "$MODE" = "project" ] || [ "$MODE" = "both" ]; then
  project_install "$PROJECT_DIR"
fi

# Disable Claude Code compatibility in OpenCode by default
if [ "$NO_PROMPT" != true ] && { [ "$MODE" = "global" ] || [ "$MODE" = "both" ]; }; then
  if [ -t 0 ]; then
    echo ""
    echo "Disable Claude Code compatibility prompt in OpenCode? (Y/n) [default: Y]:"
    echo "  Recommended to avoid conflicting rule definitions between agents."
    read -p "Choice (Y/n) [default: Y]: " disable_choice
    case "$disable_choice" in
      n|N|no|No)
        echo "  Enabling Claude Code compatibility for OpenCode (cleaning up old configs)..."
        for profile in "$HOME/.bashrc" "$HOME/.zshrc"; do
          if [ -f "$profile" ]; then
            if grep -q "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT" "$profile"; then
              sed -i '/OPENCODE_DISABLE_CLAUDE_CODE_PROMPT/d' "$profile"
              echo "    Removed from $profile"
            else
              echo "    Already clean in $profile"
            fi
          fi
        done
        ;;
      *)
        echo "  Disabling Claude Code compatibility for OpenCode..."
        for profile in "$HOME/.bashrc" "$HOME/.zshrc"; do
          if [ -f "$profile" ]; then
            if ! grep -q "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT" "$profile"; then
              echo 'export OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=true' >> "$profile"
              echo "    Added to $profile"
            else
              echo "    Already configured in $profile"
            fi
          fi
        done
        ;;
    esac
  fi
fi

echo ""
echo "=== Done ==="
echo "  Please quit and restart opencode for changes to take effect."
echo "  LSP: $([ "$LSP_ENABLED" = true ] && echo "enabled" || echo "disabled")"

if [ -t 0 ] && [ "$NO_PAUSE" != "true" ]; then
  echo ""
  read -p "Press Enter to close..."
fi
