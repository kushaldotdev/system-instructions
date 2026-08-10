#!/usr/bin/env python3
"""
pi-config-transfer — provision a fresh machine with your pi coding agent
configuration, or sync between machines. One tool, export on main, import on new.

    # Main machine: create the export (config only — NO npm/ tree, NO keys)
    python3 pi-config-transfer.py export            # -> ./pi-setup-export/

    # Copy the folder to the new machine (USB / scp / cloud)

    # New machine: FULL provisioning in one command
    python3 pi-config-transfer.py import pi-setup-export

WHAT IMPORT DOES (in order)
  1. Check/install pi itself if missing (npm install -g @earendil-works/pi-coding-agent)
  2. Restore all config files (settings.json, extensions/, models.json,
     web-search.json, config/, AGENTS.md, themes, skills, prompts, chains)
  3. pi install each package from the exported list (idempotent, deps reinstalled,
     so the export copy stays small — no node_modules bloat)
  4. Apply the pi-web-access trim patch (your provider trim, automatic)
  5. Install rtk binary, agent-browser CLI + Chrome for Testing, ffmpeg (as needed)
  6. Install pi-web (npm install -g @agegr/pi-web@latest — browser UI for pi)
  7. Print final steps (auth, keys, pi-web launch, /reload)

SYNC / DISABLED-STATE
  - settings.json is copied WHOLESALE, so disabled extensions (e.g.
    {"source": "npm:pi-mcp-adapter", "extensions": ["-index.ts"]}) stay disabled.
  - pi install reuses existing entries and never strips the "extensions" filter.

SECRETS
  - By default NO secrets are exported: auth.json (OAuth tokens), model API keys,
    tavily key — all stripped/omitted.
  - Pass --include-secrets to export them (including auth.json, the OAuth/login
    token store). The export folder then contains real keys — treat it like a
    private key.

USAGE
  export [dest] [--include-secrets] [--dry-run]    (dest defaults to ./pi-setup-export)
  import [src] [--no-install] [--dry-run]          (src defaults to ./pi-setup-export)
  list   [src]                                     show what an export contains (defaults to ./pi-setup-export)
  check                                            show environment/platform info
"""

import argparse
import fnmatch
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (mirror pi's own resolution; cross-platform)
# ---------------------------------------------------------------------------
def agent_dir() -> Path:
    """$PI_CODING_AGENT_DIR (or TAU_...) → ~/.pi/agent"""
    for env in ("PI_CODING_AGENT_DIR", "TAU_CODING_AGENT_DIR"):
        val = os.environ.get(env)
        if val:
            return Path(val).expanduser()
    return Path.home() / ".pi" / "agent"


def web_search_path() -> Path:
    for env in ("PI_CODING_AGENT_DIR", "TAU_CODING_AGENT_DIR"):
        val = os.environ.get(env)
        if val:
            return Path(val).expanduser().parent / "web-search.json"
    return Path.home() / ".pi" / "web-search.json"


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


AGENT_DIR = agent_dir()
WEB_SEARCH_PATH = web_search_path()
PI_CONFIG_DIR = AGENT_DIR.parent / "config"
BACKUP_SUFFIX = ".pi-transfer.bak"
DEFAULT_EXPORT_DIR = "pi-setup-export"

PI_NPM = "@earendil-works/pi-coding-agent"

# Top-level entries under ~/.pi/agent to sync
# auth.json (OAuth tokens) is only exported with --include-secrets (see export).
SYNC_AGENT_ITEMS = [
    "extensions", "settings.json", "models.json", "keybindings.json",
    "AGENTS.md", "SYSTEM.md", "APPEND_SYSTEM.md", "prompts", "themes", "skills", "chains", "config",
    "profiles", "auth.json",
]

# Never-sync paths inside a synced item (relative to ~/.pi/agent)
NEVER_SYNC_SUB = [
    "sessions", "state", "missions", "run-history.jsonl", "models-store.json",
    "npm", "bin", "git", "node_modules", ".git",
]

NEVER_SYNC_GLOB = ("*.log", "*.bak", "*.tmp", "*.swp", ".DS_Store", "__pycache__", "*.pyc")

SECRET_HINTS = (
    "auth", "token", "secret", "credential", "apikey", "api_key",
    "password", "passwd", ".env", "private_key", "key.json", "cookie",
)

SECRET_JSON_FIELDS = {
    "apiKey", "api_key", "apikey", "tavilyApiKey", "openaiApiKey",
    "braveApiKey", "exaApiKey", "geminiApiKey", "perplexityApiKey",
    "jinaApiKey", "kagiApiKey", "serpdiveApiKey", "search1apiApiKey",
    "searchinfinityApiKey", "queritApiKey", "tinyfishApiKey",
    "parallelApiKey", "ollamaApiKey", "cloudflareApiKey", "searxngBaseUrl",
    "access", "refresh", "headers",
}

# pi-web-access trim patch: the 2 files we patch to keep only openai/exa/tavily
TRIM_PATCH_FILES = [
    "gemini-search.ts",
    "index.ts",
]
PI_WEB_ACCESS_REL = Path("npm") / "node_modules" / "pi-web-access"


def is_secret_path(rel: str) -> bool:
    low = rel.lower()
    return any(hint in low for hint in SECRET_HINTS)


def secret_scan(path: Path) -> list:
    found = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return found
    import re
    value_pat = re.compile(
        r'("[^"]*(?:api|key|token|secret|password)[^"]*"|\w*[Kk]ey\w*)\s*[:=]\s*"([^"]{12,})"'
    )
    for i, line in enumerate(text.splitlines(), 1):
        if value_pat.search(line):
            found.append((i, line.strip()[:80]))
    return found


def strip_secrets_from_json(src: Path, out: Path) -> None:
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError(f"unreadable JSON: {src}")

    def walk(node):
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if k in SECRET_JSON_FIELDS:
                    node[k] = "***REDACTED***"
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_settings() -> dict:
    p = AGENT_DIR / "settings.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def package_sources() -> list:
    """Extract the package sources list (string or object) from settings.json."""
    return load_settings().get("packages", [])


def collect_files() -> list:
    """Return list of (rel_path, is_dir) to export from the agent dir."""
    result = []
    for item in SYNC_AGENT_ITEMS:
        src = AGENT_DIR / item
        if not src.exists():
            continue
        if src.is_dir():
            for root, dirs, files in os.walk(src):
                rel_dir = Path(root).relative_to(AGENT_DIR)
                dirs[:] = [d for d in dirs if rel_dir / d not in NEVER_SYNC_SUB]
                for f in files:
                    if any(fnmatch.fnmatch(f, pat) for pat in NEVER_SYNC_GLOB):
                        continue
                    result.append((str(rel_dir / f), False))
        else:
            result.append((item, False))
    # web-search.json (outside agent dir)
    if WEB_SEARCH_PATH.exists():
        result.append(("web-search.json", False))
    # agent-browser config (~/.pi/config/)
    for root, dirs, files in os.walk(PI_CONFIG_DIR):
        rel_dir = Path(root).relative_to(PI_CONFIG_DIR)
        for f in files:
            if any(fnmatch.fnmatch(f, pat) for pat in NEVER_SYNC_GLOB):
                continue
            result.append((f"config/{rel_dir / f}", False))
    return sorted(result)


def resolve_src(rel: str) -> Path:
    if rel == "web-search.json":
        return WEB_SEARCH_PATH
    if rel.startswith("config/"):
        return PI_CONFIG_DIR / rel[len("config/"):]
    return AGENT_DIR / rel


def resolve_target(rel: str) -> Path:
    if rel == "web-search.json":
        return WEB_SEARCH_PATH
    if rel.startswith("config/"):
        return PI_CONFIG_DIR / rel[len("config/"):]
    return AGENT_DIR / rel


# ---------------------------------------------------------------------------
# Command runners
# ---------------------------------------------------------------------------
def run(cmd: list, check=True, capture=False):
    """Run a command, inheriting stdout. Returns (code, output) when capture."""
    try:
        res = subprocess.run(cmd, capture_output=capture, text=True)
        if check and res.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} failed (code {res.returncode})")
        return res
    except FileNotFoundError:
        if check:
            raise RuntimeError(f"command not found: {cmd[0]}")
        return None


def is_pi_installed() -> bool:
    return shutil.which("pi") is not None


def ensure_pi() -> None:
    """Install pi globally if missing."""
    if is_pi_installed():
        print("[=] pi already installed")
        return
    print("[+] pi not found — installing @earendil-works/pi-coding-agent globally...")
    res = run(["npm", "install", "-g", PI_NPM], check=False)
    if res is not None and res.returncode == 0 and is_pi_installed():
        print("[+] pi installed")
    else:
        raise RuntimeError("Could not install pi. Manual: npm install -g @earendil-works/pi-coding-agent")


def pi_install_packages(packages: list) -> None:
    """pi install each package source. Idempotent; keeps disabled-extension filters."""
    if not packages:
        print("[=] no packages to install")
        return
    print(f"\n-> Installing {len(packages)} package(s) via pi install...")
    for pkg in packages:
        source = pkg if isinstance(pkg, str) else pkg.get("source", "")
        if not source:
            continue
        print(f"  pi install {source}")
        res = run(["pi", "install", source], check=False)
        if res is not None and res.returncode != 0:
            print(f"    ⚠️  failed to install {source}")


def ensure_rtk() -> None:
    if shutil.which("rtk"):
        print("[=] rtk already installed")
        return
    print("[+] rtk not found — installing (official installer)...")
    res = run(["bash", "-lc", "curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh"], check=False)
    if res is not None and res.returncode == 0 and shutil.which("rtk"):
        print("[+] rtk installed")
    else:
        print("  ⚠️  rtk install failed. Manual: curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh")


def ensure_agent_browser() -> None:
    if shutil.which("agent-browser"):
        print("[=] agent-browser CLI already installed")
    else:
        print("[+] agent-browser CLI not found — npm install -g agent-browser...")
        res = run(["npm", "install", "-g", "agent-browser"], check=False)
        if res is None or res.returncode != 0:
            print("  ⚠️  agent-browser CLI install failed. Manual: npm install -g agent-browser")
            return
        print("[+] agent-browser CLI installed")

    # Chrome for Testing
    browsers_dir = Path.home() / ".agent-browser" / "browsers"
    chrome_present = browsers_dir.exists() and any(
        e.name.startswith("chrome-") for e in browsers_dir.iterdir()
    ) if browsers_dir.exists() else False
    if chrome_present:
        print("[=] Chrome for Testing already present")
    else:
        print("[+] Chrome for Testing missing — running 'agent-browser install' (one-time download)...")
        res = run(["agent-browser", "install"], check=False)
        if res is None or res.returncode != 0:
            print("  ⚠️  'agent-browser install' failed. On Linux/WSL you may need:\n      sudo agent-browser install --with-deps")


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        print("[=] ffmpeg available")
    else:
        print("  ⚠️  ffmpeg not found — browser screen recording ('record stop') needs it.")
        print("      Linux/WSL: sudo apt install ffmpeg | macOS: brew install ffmpeg | Windows: winget install ffmpeg")


PI_WEB_NPM = "@agegr/pi-web"


def ensure_pi_web() -> None:
    """Install the pi browser UI (pi-web) globally if missing."""
    if shutil.which("pi-web"):
        print("[=] pi-web already installed")
        return
    print(f"[+] pi-web not found — npm install -g {PI_WEB_NPM}@latest...")
    res = run(["npm", "install", "-g", f"{PI_WEB_NPM}@latest"], check=False)
    if res is not None and res.returncode == 0 and shutil.which("pi-web"):
        print("[+] pi-web installed")
    else:
        print(f"  ⚠️  pi-web install failed. Manual: npm install -g {PI_WEB_NPM}@latest")
        print("      Note: pi-web requires Node.js 22.19.0 or newer.")


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------
def export_config(dest: str, include_secrets: bool, dry_run: bool) -> int:
    dest_path = Path(dest).expanduser()
    files = collect_files()

    if dry_run:
        # Mirror real export: secret paths are only included with --include-secrets
        shown = [(rel, _) for rel, _ in files if not (is_secret_path(rel) and not include_secrets)]
        print(f"[dry-run] Would export {len(shown)} item(s) to {dest_path}")
        for rel, _ in shown:
            print(f"  + {rel}")
        skipped = [rel for rel, _ in files if is_secret_path(rel) and not include_secrets]
        if skipped:
            print(f"  ⚠️  Skipped (secret, use --include-secrets): {', '.join(skipped)}")
        # Show packages + patch too
        pkgs = package_sources()
        print(f"\n  package list ({len(pkgs)}):")
        for p in pkgs:
            print(f"    - {p if isinstance(p, str) else p.get('source')}")
        return 0

    if dest_path.exists() and any(dest_path.iterdir()):
        print(f"error: {dest_path} is not empty — use a new folder or empty it first")
        return 2

    dest_path.mkdir(parents=True, exist_ok=True)
    copied = []
    skipped_secret = []
    warnings = []

    for rel, _ in files:
        src = resolve_src(rel)
        if is_secret_path(rel):
            if not include_secrets:
                skipped_secret.append(rel)
                continue
        if not include_secrets and src.suffix == ".json" and rel in ("web-search.json", "models.json"):
            try:
                strip_secrets_from_json(src, dest_path / rel)
            except ValueError as e:
                warnings.append(f"{rel}: {e} — skipped")
                continue
            copied.append(rel + " (secrets stripped)")
            continue
        target = dest_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(rel)
        # auth.json is only copied when --include-secrets was passed, so its
        # secret-shaped values are expected — don't warn about them.
        if include_secrets and rel == "auth.json":
            continue
        if src.suffix in (".json", ".jsonc", ".md", ".txt", ".ts", ".js"):
            hits = secret_scan(target)
            if hits:
                warnings.append(f"{rel}: possible secret at line(s) {', '.join(str(h) for h in [x[0] for x in hits])}")

    # Package list (for import to pi install) — always exported
    pkgs = package_sources()
    (dest_path / "packages.json").write_text(
        json.dumps({"packages": pkgs}, indent=2) + "\n", encoding="utf-8")

    # Trim patch (pi-web-access) — always exported, so import can re-apply
    patch_dir = dest_path / "patch" / "pi-web-access"
    for fname in TRIM_PATCH_FILES:
        src_patch = AGENT_DIR / PI_WEB_ACCESS_REL / fname
        bak = Path(str(src_patch) + ".web-search-trim.bak")
        if src_patch.exists():
            patch_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_patch, patch_dir / fname)
            if bak.exists():
                shutil.copy2(bak, patch_dir / (fname + ".bak"))
            copied.append(f"patch/pi-web-access/{fname}")
        else:
            warnings.append(f"trim patch source missing: {fname} (pi-web-access not installed?)")

    manifest = {
        "tool": "pi-config-transfer", "version": "2.1.0",
        "exportedAt": __import__("datetime").datetime.now().isoformat(),
        "hostname": hostname(), "includeSecrets": include_secrets,
        "items": [r for r, _ in files if not (is_secret_path(r) and not include_secrets)],
        "packages": pkgs,
        "patch": [f"patch/pi-web-access/{f}" for f in TRIM_PATCH_FILES],
    }
    (dest_path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"✅ Exported {len(copied)} item(s) + {len(pkgs)} package(s) + trim patch → {dest_path}")
    for c in copied:
        print(f"  + {c}")
    if skipped_secret:
        print(f"\n⚠️  Skipped (secret, use --include-secrets to bring): {', '.join(skipped_secret)}")
    if warnings:
        print("\n⚠️  Warnings:")
        for w in warnings:
            print(f"  - {w}")
    print("\nNext: copy this folder to the new machine, then run:")
    print(f"  python3 pi-config-transfer.py import {dest}")
    return 0


# ---------------------------------------------------------------------------
# IMPORT
# ---------------------------------------------------------------------------
def import_config(src: str, dry_run: bool, no_install: bool) -> int:
    src_path = Path(src).expanduser()
    manifest_path = src_path / "manifest.json"
    if not src_path.is_dir() or not manifest_path.exists():
        print(f"error: {src_path} doesn't look like a pi-config-transfer export (no manifest.json)")
        return 2

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        print(f"error: cannot read {manifest_path}")
        return 2

    items = manifest.get("items", [])
    if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
        print(f"error: {manifest_path} has no valid items list")
        return 2
    print(f"Export from {manifest.get('hostname', '?')} @ {manifest.get('exportedAt', '?')}")
    print(f"  {len(items)} item(s), secrets={'included' if manifest.get('includeSecrets') else 'NOT included'}\n")

    # 1. Ensure pi
    if not no_install:
        print("=== Step 1/7: pi itself ===")
        ensure_pi()

    # 2. Restore config files
    print("\n=== Step 2/7: config files ===")
    to_apply = []
    for root, dirs, files in os.walk(src_path):
        # skip .git and patch dirs (patch handled separately)
        dirs[:] = [d for d in dirs if d not in (".git", "patch")]
        for f in files:
            if f == "manifest.json" or f == "packages.json":
                continue
            if any(fnmatch.fnmatch(f, pat) for pat in NEVER_SYNC_GLOB):
                continue
            rel = Path(root).relative_to(src_path)
            to_apply.append(rel / f)

    if dry_run:
        print(f"[dry-run] Would apply {len(to_apply)} file(s)")
        for p in to_apply:
            print(f"  + {p}")
        return 0

    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    applied = []
    for rel in to_apply:
        src_file = src_path / rel
        target = resolve_target(str(rel))
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            bak = target.with_suffix(target.suffix + BACKUP_SUFFIX)
            try:
                shutil.copy2(target, bak)
            except OSError:
                pass
        shutil.copy2(src_file, target)
        applied.append(str(rel))
    print(f"✅ Restored {len(applied)} file(s)")
    for a in applied:
        print(f"  + {a}")

    # 3. Install packages (only if not --no-install and not dry-run)
    if not no_install:
        print("\n=== Step 3/7: packages ===")
        pkgs_path = src_path / "packages.json"
        pkgs = []
        if pkgs_path.exists():
            try:
                pkgs = json.loads(pkgs_path.read_text(encoding="utf-8")).get("packages", [])
            except (OSError, json.JSONDecodeError):
                pass
        pi_install_packages(pkgs)

    # 4. Apply trim patch
    if not no_install:
        print("\n=== Step 4/7: pi-web-access trim patch ===")
        patch_src = src_path / "patch" / "pi-web-access"
        if patch_src.exists():
            target_dir = AGENT_DIR / PI_WEB_ACCESS_REL
            target_dir.mkdir(parents=True, exist_ok=True)
            for fname in TRIM_PATCH_FILES:
                pf = patch_src / fname
                if pf.exists():
                    shutil.copy2(pf, target_dir / fname)
                    print(f"  + patched {fname} (provider trim applied)")
        else:
            print("  - no patch in export (skipped)")

    # 5. Binaries (rtk, agent-browser, ffmpeg)
    if not no_install:
        print("\n=== Step 5/7: binaries ===")
        ensure_rtk()
        ensure_agent_browser()
        ensure_ffmpeg()

    # 6. pi-web (browser UI)
    if not no_install:
        print("\n=== Step 6/7: pi-web ===")
        ensure_pi_web()

    # 7. Final notes
    print("\n=== Step 7/7: final notes ===")
    if manifest.get("includeSecrets"):
        print("  1. Secrets INCLUDED in this export: auth.json (login tokens), web-search.json,")
        print("     models.json apiKeys were copied as-is.")
        print("  2. You should already be logged in (auth.json restored) — verify with 'pi auth status'.")
        print("  3. Run /reload inside pi to load the imported extensions.")
        print("  4. Browser UI: run 'pi-web' then open http://127.0.0.1:30141")
    else:
        print("  1. Keys/auth NOT copied (by default). To bring them, re-export with --include-secrets.")
        print("     auth.json (OAuth/login tokens) is now included with --include-secrets too.")
        print("  2. Add keys: ~/.pi/web-search.json (tavilyApiKey) and ~/.pi/agent/models.json (apiKey).")
        print("  3. Log in: run 'pi' → /auth (or 'pi auth login') for Codex/OpenAI.")
        print("  4. Run /reload inside pi to load the imported extensions.")
        print("  5. Browser UI: run 'pi-web' then open http://127.0.0.1:30141")
    print("\n✅ Provisioning complete!")
    return 0


# ---------------------------------------------------------------------------
# LIST / CHECK
# ---------------------------------------------------------------------------
def list_export(src: str) -> int:
    src_path = Path(src).expanduser()
    manifest_path = src_path / "manifest.json"
    if not manifest_path.exists():
        print(f"error: {src_path} doesn't look like an export (no manifest.json)")
        return 2
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        print(f"error: cannot read {manifest_path}")
        return 2
    items = manifest.get("items", [])
    if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
        print(f"error: {manifest_path} has no valid items list")
        return 2
    print(f"Export: {manifest.get('hostname', '?')} @ {manifest.get('exportedAt', '?')}")
    print(f"  Secrets included: {manifest.get('includeSecrets', False)}")
    print(f"  Packages ({len(manifest.get('packages', []))}):")
    for p in manifest.get("packages", []):
        print(f"    - {p if isinstance(p, str) else p.get('source')}")
    print(f"  Items ({len(items)}):")
    for item in items:
        print(f"    - {item}")
    return 0


def check_environment() -> int:
    import platform
    print("=== pi-config-transfer environment check ===")
    print(f"  Platform        : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  Python          : {platform.python_version()}")
    if os.environ.get("WSL_DISTRO_NAME"):
        print(f"  WSL             : yes ({os.environ.get('WSL_DISTRO_NAME')})")
    print(f"  Agent dir       : {AGENT_DIR}")
    print(f"  web-search.json : {WEB_SEARCH_PATH}")
    print(f"  config dir      : {PI_CONFIG_DIR}")
    print(f"  python cmd      : {'python' if platform.system() == 'Windows' else 'python3'}")
    for tool in ("git", "pi", "node", "npm", "rtk", "agent-browser", "ffmpeg", "pi-web"):
        found = shutil.which(tool)
        print(f"  {tool:<14}: {found or 'NOT FOUND'}")
    for name, p in (("agent dir", AGENT_DIR), ("web-search", WEB_SEARCH_PATH), ("config", PI_CONFIG_DIR)):
        print(f"  {'exists ' + name:<20}: {'yes' if p.exists() else 'no'}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="pi-config-transfer",
        description="Provision/sync pi coding agent config across machines.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="create an export folder")
    p_export.add_argument("dest", nargs="?", default=DEFAULT_EXPORT_DIR)
    p_export.add_argument("--include-secrets", action="store_true")
    p_export.add_argument("--dry-run", action="store_true")

    p_import = sub.add_parser("import", help="provision a machine from an export")
    p_import.add_argument("src", nargs="?", default=DEFAULT_EXPORT_DIR,
                          help=f"source export folder (default: {DEFAULT_EXPORT_DIR}/ in current dir)")
    p_import.add_argument("--no-install", action="store_true", help="config only, skip pi/packages/binaries")
    p_import.add_argument("--dry-run", action="store_true")

    p_list = sub.add_parser("list", help="inspect an export folder")
    p_list.add_argument("src", nargs="?", default=DEFAULT_EXPORT_DIR,
                        help=f"source export folder (default: {DEFAULT_EXPORT_DIR}/ in current dir)")
    sub.add_parser("check", help="show environment/platform info")

    args = parser.parse_args()

    if args.command == "export":
        sys.exit(export_config(args.dest, args.include_secrets, args.dry_run))
    elif args.command == "import":
        sys.exit(import_config(args.src, args.dry_run, args.no_install))
    elif args.command == "list":
        sys.exit(list_export(args.src))
    elif args.command == "check":
        sys.exit(check_environment())


if __name__ == "__main__":
    main()
