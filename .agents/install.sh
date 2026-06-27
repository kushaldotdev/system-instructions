#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CENTRAL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSP="$CENTRAL_ROOT/.agents/SYSTEM_PROMPT.md"
RULES="$CENTRAL_ROOT/.agents/RULES.md"
INST="$CENTRAL_ROOT/INSTRUCTIONS.md"
CHECKPOINT_TEMPLATE="$CENTRAL_ROOT/.agents/CHECKPOINT.md.template"

# === Args ===
MODE=""
PROJECT_DIR=""
NO_PAUSE=false
FORCE=false
while [ $# -gt 0 ]; do
  case "$1" in
    --global) MODE="global"; shift ;;
    --project) MODE="project"; shift; PROJECT_DIR="${1:-}"; [ -z "$PROJECT_DIR" ] && { echo "Usage: --project <dir>"; exit 1; }; shift ;;
    --no-pause) NO_PAUSE=true; shift ;;
    --force) FORCE=true; shift ;;
    --help|-h) echo "Usage: bash install.sh [--global|--project <dir>] [--force] [--no-pause]"; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

echo "============================================"
echo "  .agents Workflow Installer"
echo "  Central: $CENTRAL_ROOT/.agents/"
echo "============================================"
echo ""

# === Interactive mode ===
if [ -z "$MODE" ]; then
  echo "Install mode:"
  echo "  g) Global -- applies to ALL projects on this machine"
  echo "  p) Project -- bridges in a specific project"
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

# === Tool selection ===
echo "Select tools (e.g. 1 3 5 or a for all):"
echo "  1) opencode"
echo "  2) claude-code"
echo "  3) antigravity"
echo "  4) codex"
echo "  5) cline"
echo "  6) kilo-code"
echo "  a) all | q) quit"
read -p "> " selection
selection=$(echo "$selection" | tr ',' ' ')
[ "$selection" = "q" ] && exit 0
[ "$selection" = "a" ] && selection="1 2 3 4 5 6"

# === Instructions format ===
echo ""
echo "Instructions format:"
echo "  m) Modular -- SYSTEM_PROMPT.md + RULES.md (two files, ~600t + ~1,100t on-demand)"
echo "  s) Standalone -- INSTRUCTIONS.md (single merged file, ~1,700t always loaded)"
read -p "Choice (m/s): " fmt
case "$fmt" in
  m|M)
    FORMAT="modular"
    INSTR_FILES="$SYSP
  - $RULES"
    INSTR_TEXT="SYSTEM_PROMPT.md and RULES.md"
    OCFILE1="$SYSP"
    OCFILE2="$RULES"
    AG_SYMLINKS="SYSTEM_PROMPT.md RULES.md"
    AG_LINK_SRC1="$SYSP"
    AG_LINK_SRC2="$RULES"
    ;;
  s|S)
    FORMAT="standalone"
    INSTR_FILES="  - $INST"
    INSTR_TEXT="INSTRUCTIONS.md"
    OCFILE1="$INST"
    OCFILE2=""
    AG_SYMLINKS="INSTRUCTIONS.md"
    AG_LINK_SRC1="$INST"
    AG_LINK_SRC2=""
    ;;
  *) echo "Invalid"; exit 1 ;;
esac

# === LSP for opencode ===
echo ""
echo "Enable LSP for opencode? (y/N):"
echo "  LSP provides diagnostics and symbol intelligence when reading files."
echo "  Note: adds small token overhead (diagnostic messages per file)."
read -p "Choice (y/N): " lsp_choice
case "$lsp_choice" in
  y|Y|yes|Yes) LSP_ENABLED=true ;;
  *) LSP_ENABLED=false ;;
esac

# === Global detection ===
global_path_for_tool() {
  case "$1" in
    1) echo "$HOME/.config/opencode/opencode.jsonc" ;;
    2) echo "$HOME/.claude/CLAUDE.md" ;;
    3) echo "$HOME/.gemini/GEMINI.md" ;;
    4) echo "$HOME/.codex/AGENTS.md" ;;
    5)
      if [ "$(uname)" = "Linux" ] || [ "$(uname)" = "Darwin" ]; then
        echo "$HOME/Documents/Cline/Rules/000-system-instructions.md"
      else
        echo "$HOME/Cline/Rules/000-system-instructions.md"
      fi
      ;;
    6) echo "$HOME/.config/kilo/kilo.jsonc" ;;
  esac
}

is_globally_installed() {
  local f=$(global_path_for_tool "$1")
  [ -f "$f" ] || [ -L "$f" ]
}

# === Write instruct bridge (direct write for single-file tools) ===
write_instruct_bridge() {
  local file="$1"
  local label="$2"
  local dir="$(dirname "$file")"
  mkdir -p "$dir"

  # Check existing file (preserve custom content unless --force)
  if [ -f "$file" ]; then
    read -r first_line < "$file"
    first_line="${first_line#$'\xef\xbb\xbf'}"
    if [ "$first_line" != "# AI Behavior Rules" ] && [ "$FORCE" != true ]; then
      echo "    [skip]  $file (custom content exists, use --force to overwrite)"
      return
    fi
  fi

  if [ "$FORMAT" = "modular" ]; then
    # Copy RULES.md and CHECKPOINT.md.template (not SYSTEM_PROMPT.md -- it IS the file)
    cp -f "$RULES" "$dir/RULES.md"
    cp -f "$CHECKPOINT_TEMPLATE" "$dir/CHECKPOINT.md.template"
    # Write SYSP content with marker header + path substitution
    { echo "# AI Behavior Rules"
      sed -e "s|\.agents/RULES\.md|$dir/RULES.md|g" \
          -e "s|\.agents/CHECKPOINT\.md\.template|$dir/CHECKPOINT.md.template|g" \
          "$SYSP"
    } > "$file"
  else
    # Write INST content with marker header (fully self-contained)
    { echo "# AI Behavior Rules"
      cat "$INST"
    } > "$file"
  fi
  echo "    [write] $file"
  # Clean up any old SYSTEM_PROMPT.md copy that is no longer needed
  rm -f "$dir/SYSTEM_PROMPT.md" 2>/dev/null || true
}

jsonc_instructions() {
  local target="$1"
  local filename="$2"
  local label="$3"
  local add_lsp="${4:-false}"
  local json="$target/$filename"

  cp -f "$SYSP" "$target/SYSTEM_PROMPT.md"
  cp -f "$RULES" "$target/RULES.md"
  cp -f "$CHECKPOINT_TEMPLATE" "$target/CHECKPOINT.md.template"
  echo "    [copy]   $target/SYSTEM_PROMPT.md, $target/RULES.md, $target/CHECKPOINT.md.template"

  sed -i "s|\\.agents/RULES\\.md|$target/RULES.md|g" "$target/SYSTEM_PROMPT.md"
  sed -i "s|\\.agents/CHECKPOINT\\.md\\.template|$target/CHECKPOINT.md.template|g" "$target/SYSTEM_PROMPT.md"

  local sysp_quoted="\"$target/SYSTEM_PROMPT.md\""
  local perm_path="$target/*.md"

  local ext_dir_pattern=""
  if [ "$label" = "global" ]; then
    local tool_dir="${filename%.jsonc*}"
    ext_dir_pattern="~/.config/$tool_dir/**"
  fi

  if [ -f "$json" ]; then
    local changed=false
    local tmp="$json.tmp"

    # --- fix instructions (only SYSTEM_PROMPT.md, no RULES.md) ---
    grep -q '"instructions".*RULES\.md' "$json" 2>/dev/null && local has_rules=true || local has_rules=false
    grep -q '"instructions"' "$json" 2>/dev/null && local has_inst=true || local has_inst=false

    if [ "$has_rules" = true ]; then
      awk -v new="  \"instructions\": [\n    $sysp_quoted\n  ]" '
        /"instructions"/ { skip = 1 }
        skip && /\]/ { print new; skip = 0; next }
        !skip { print }
      ' "$json" > "$tmp" && mv "$tmp" "$json"
      changed=true
    elif [ "$has_inst" = false ]; then
      awk -v new="  \"instructions\": [\n    $sysp_quoted\n  ]" '
        { lines[NR] = $0 }
        END {
          depth = 0; last = 0
          for (i = 1; i <= NR; i++) {
            line = lines[i]
            for (j = 1; j <= length(line); j++) {
              c = substr(line, j, 1)
              if (c == "{") depth++
              if (c == "}") { depth--; if (depth == 0) last = i }
            }
          }
          for (k = last - 1; k >= 1; k--) {
            if (lines[k] !~ /^[[:space:]]*$/) {
              if (lines[k] !~ /,$/) sub(/[[:space:]]*$/, ",", lines[k])
              break
            }
          }
          for (i = 1; i <= NR; i++) {
            if (i == last) { print new }
            print lines[i]
          }
        }
      ' "$json" > "$tmp" && mv "$tmp" "$json"
      changed=true
    fi

    # --- fix read permission for *.md ---
    if ! grep -qF "$perm_path" "$json" 2>/dev/null; then
      grep -q '"permission"' "$json" 2>/dev/null && local has_perm=true || local has_perm=false

      if [ "$has_perm" = true ]; then
        awk -v perm="$perm_path" '
          /"permission"/ {
            ins = 1
            depth = 0
            for (j = 1; j <= length($0); j++) {
              c = substr($0, j, 1)
              if (c == "{") depth++
              if (c == "}") depth--
            }
            print; next
          }
          ins {
            for (j = 1; j <= length($0); j++) {
              c = substr($0, j, 1)
              if (c == "{") depth++
              if (c == "}") depth--
            }
            if (depth == 0) {
              printf "    \"read\": {\n"
              printf "      \"" perm "\": \"allow\"\n"
              printf "    },\n"
              print
              ins = 0
              next
            } else { print; prev = $0 }
          }
          !ins { print }
        ' "$json" > "$tmp" && mv "$tmp" "$json"
      else
        awk -v perm="$perm_path" -v ext_dir="$ext_dir_pattern" '
          { lines[NR] = $0 }
          END {
            depth = 0; last = 0
            for (i = 1; i <= NR; i++) {
              line = lines[i]
              for (j = 1; j <= length(line); j++) {
                c = substr(line, j, 1)
                if (c == "{") depth++
                if (c == "}") { depth--; if (depth == 0) last = i }
              }
            }
            for (k = last - 1; k >= 1; k--) {
              if (lines[k] !~ /^[[:space:]]*$/) {
                if (lines[k] !~ /,$/) sub(/[[:space:]]*$/, ",", lines[k])
                break
              }
            }
            for (i = 1; i <= NR; i++) {
              if (i == last) {
                print "  \"permission\": {"
                print "    \"read\": {"
                print "      \"" perm "\": \"allow\""
                if (ext_dir != "") {
                  print "    },"
                  print "    \"external_directory\": {"
                  print "      \"" ext_dir "\": \"allow\""
                  print "    }"
                } else {
                  print "    }"
                }
                print "  }"
              }
              print lines[i]
            }
          }
        ' "$json" > "$tmp" && mv "$tmp" "$json"
      fi
      changed=true
    fi

    # --- fix external_directory for global configs ---
    if [ -n "$ext_dir_pattern" ] && ! grep -q '"external_directory"' "$json" 2>/dev/null; then
      awk -v ext_dir="$ext_dir_pattern" '
        /"permission"/ {
          ins = 1
          depth = 0
          for (j = 1; j <= length($0); j++) {
            c = substr($0, j, 1)
            if (c == "{") depth++
            if (c == "}") depth--
          }
          print; next
        }
        ins {
          for (j = 1; j <= length($0); j++) {
            c = substr($0, j, 1)
            if (c == "{") depth++
            if (c == "}") depth--
          }
          if (depth == 0) {
              printf "    \"external_directory\": {\n"
              printf "      \"%s\": \"allow\"\n", ext_dir
              printf "    }\n"
              print
              ins = 0
              next
            } else { print; prev = $0 }
        }
        !ins { print }
      ' "$json" > "$tmp" && mv "$tmp" "$json"
      changed=true
    fi

    # --- fix lsp for opencode ---
    if [ "$add_lsp" = true ] && ! grep -q '"lsp"' "$json" 2>/dev/null; then
      awk '
        /^[[:space:]]*"permission"/ {
          print "  \"lsp\": true,"
          print; next
        }
        { print }
      ' "$json" > "$tmp" && mv "$tmp" "$json"
      changed=true
    fi

    if [ "$changed" = true ]; then
      echo "    [update] $json"
    else
      echo "    [ok]     $json"
    fi
  else
    local ext_dir_json=""
    local lsp_json=""
    if [ -n "$ext_dir_pattern" ]; then
      ext_dir_json=",
    \"external_directory\": {
      \"$ext_dir_pattern\": \"allow\"
    }"
    fi
    if [ "$add_lsp" = true ]; then
      lsp_json=$'\n  "lsp": true,'
    fi
    cat > "$json" <<-EOF
{
  "instructions": [
    $sysp_quoted
  ],$lsp_json
  "permission": {
    "read": {
      "$perm_path": "allow"
    }$ext_dir_json
  }
}
EOF
    echo "    [create] $json"
  fi
}

antigravity_project() {
  local target="$1"
  local rules_dir="$target/.agent/rules"
  mkdir -p "$rules_dir"

  if [ "$FORMAT" = "modular" ]; then
    for f in SYSTEM_PROMPT.md RULES.md; do
      local link="$rules_dir/$f"
      local src="$CENTRAL_ROOT/.agents/$f"
      if [ -e "$link" ] || [ -L "$link" ]; then
        echo "    [exists] $link"
      else
        ln -s "$src" "$link"
        echo "    [link]   $link -> $src"
      fi
    done
  else
    local link="$rules_dir/INSTRUCTIONS.md"
    if [ -e "$link" ] || [ -L "$link" ]; then
      echo "    [exists] $link"
    else
      ln -s "$INST" "$link"
      echo "    [link]   $link -> $INST"
    fi
  fi
}

# =============================================================
# GLOBAL INSTALL
# =============================================================
global_install() {
  local sel="$1"
  case "$sel" in
    1)
      echo "  -- opencode (global)"
      mkdir -p "$HOME/.config/opencode"
      jsonc_instructions "$HOME/.config/opencode" "opencode.jsonc" "global" "$LSP_ENABLED"
      ;;
    2)
      echo "  -- claude-code (global)"
      mkdir -p "$HOME/.claude"
      write_instruct_bridge "$HOME/.claude/CLAUDE.md" "Claude Code (global)"
      ;;
    3)
      echo "  -- antigravity (global)"
      mkdir -p "$HOME/.gemini"
      write_instruct_bridge "$HOME/.gemini/GEMINI.md" "Antigravity (global)"
      ;;
    4)
      echo "  -- codex (global)"
      mkdir -p "$HOME/.codex"
      write_instruct_bridge "$HOME/.codex/AGENTS.md" "Codex (global)"
      ;;
    5)
      echo "  -- cline (global)"
      local cline_dir
      if [ "$(uname)" = "Linux" ] || [ "$(uname)" = "Darwin" ]; then
        cline_dir="$HOME/Documents/Cline/Rules"
      else
        cline_dir="$HOME/Cline/Rules"
      fi
      mkdir -p "$cline_dir"
      write_instruct_bridge "$cline_dir/000-system-instructions.md" "Cline (global)"
      ;;
    6)
      echo "  -- kilo-code (global)"
      mkdir -p "$HOME/.config/kilo"
      jsonc_instructions "$HOME/.config/kilo" "kilo.jsonc" "global"
      ;;
  esac
}

# =============================================================
# PROJECT INSTALL
# =============================================================
project_install() {
  local target="$1"
  local sel="$2"

  if is_globally_installed "$sel"; then
    local label
    case "$sel" in
      1) label="opencode" ;; 2) label="claude-code" ;; 3) label="antigravity" ;; 4) label="codex" ;;       5) label="cline" ;;
      6) label="kilo-code" ;;
    esac
    echo "  -- $label (project) -- SKIPPED (global already installed)"
    return
  fi

  case "$sel" in
    1)
      echo "  -- opencode (project)"
      jsonc_instructions "$target" "opencode.jsonc" "project" "$LSP_ENABLED"
      ;;
    2)
      echo "  -- claude-code (project)"
      write_instruct_bridge "$target/CLAUDE.md" "Project Instructions"
      ;;
    3)
      echo "  -- antigravity (project)"
      antigravity_project "$target"
      ;;
    4)
      echo "  -- codex (project)"
      write_instruct_bridge "$target/AGENTS.md" "Project Instructions"
      ;;
    5)
      echo "  -- cline (project)"
      write_instruct_bridge "$target/.clinerules" "Project Instructions"
      ;;
    6)
      echo "  -- kilo-code (project)"
      jsonc_instructions "$target" "kilo.jsonc" "project"
      ;;
  esac
}

# =============================================================
# EXECUTE
# =============================================================
for sel in $selection; do
  echo ""
  if [ "$MODE" = "global" ] || [ "$MODE" = "both" ]; then
    global_install "$sel"
  fi
  if [ "$MODE" = "project" ] || [ "$MODE" = "both" ]; then
    project_install "$PROJECT_DIR" "$sel"
  fi
done

echo ""
echo "=== Done ==="
echo "  Format: $FORMAT ($INSTR_TEXT)"
echo "  LSP: $([ "$LSP_ENABLED" = true ] && echo "enabled for opencode" || echo "disabled")"
if [ "$MODE" = "global" ] || [ "$MODE" = "both" ]; then
  echo "  Global: bridges installed. Re-run to refresh: $SCRIPT_DIR/install.sh --global [--force]"
fi
if [ "$MODE" = "project" ] || [ "$MODE" = "both" ]; then
  echo "  Project: bridges in $PROJECT_DIR"
fi

if [ -t 0 ] && [ "$NO_PAUSE" != "true" ]; then
  echo ""
  read -p "Press Enter to close..."
fi
