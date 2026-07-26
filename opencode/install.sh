#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# === Args ===
MODE=""
PROJECT_DIR=""
NO_PAUSE=false
while [ $# -gt 0 ]; do
  case "$1" in
    --global) MODE="global"; shift ;;
    --project) MODE="project"; shift; PROJECT_DIR="${1:-}"; [ -z "$PROJECT_DIR" ] && { echo "Usage: --project <dir>"; exit 1; }; shift ;;
    --no-pause) NO_PAUSE=true; shift ;;
    --help|-h) echo "Usage: bash install.sh [--global|--project <dir>] [--no-pause]"; exit 0 ;; 
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

echo "============================================"
echo "  opencode Custom Modes Installer"
echo "============================================"
echo ""

# === Interactive mode ===
if [ -z "$MODE" ]; then
  echo "Install mode:"
  echo "  g) Global -- applies to ALL projects on this machine"
  echo "  p) Project -- installs in a specific project"
  echo "  b) Both"
  echo "  q) Quit"
  read -p "Choice (g/p/b/q): " mc
  case "$mc" in g|G) MODE="global" ;; p|P) MODE="project" ;; b|B) MODE="both" ;; q|Q) exit 0 ;; *) echo "Invalid"; exit 1 ;; esac
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
  python3 << 'PYEOF'
import json, re, os

target = os.environ['OP_TARGET']
inst_path = os.environ['OP_INST_PATH']
config_path = os.environ['OP_CONFIG']
script_dir = os.environ['OP_SCRIPT_DIR']

agents_json_path = os.path.join(script_dir, 'agents.json')
with open(agents_json_path, 'r') as f:
    agent_defs = json.load(f)

if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        raw = f.read()
    cleaned = re.sub(
        r'"(?:\\.|[^"\\])*"|(//[^\n]*\n?|/\*.*?\*/)',
        lambda m: '' if m.group(1) else m.group(0),
        raw,
        flags=re.S
    )
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        data = json.loads(cleaned)
    except Exception:
        data = {}
    if 'instructions' not in data or not isinstance(data['instructions'], list):
        data['instructions'] = []
    if inst_path not in data['instructions']:
        data['instructions'].append(inst_path)
    action = 'update'
else:
    data = {
        '$schema': 'https://opencode.ai/config.json',
        'instructions': [inst_path]
    }
    action = 'create'

if 'agent' not in data or not isinstance(data['agent'], dict):
    data['agent'] = {}
data['agent'].update(agent_defs)

with open(config_path, 'w') as f:
    json.dump(data, f, indent=2)

print(f'    [{action}] {config_path}')
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

echo ""
echo "=== Done ==="
echo "  Please quit and restart opencode for changes to take effect."

if [ -t 0 ] && [ "$NO_PAUSE" != "true" ]; then
  echo ""
  read -p "Press Enter to close..."
fi
