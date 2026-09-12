/**
 * Cross-Platform Command & Action Guard Extension for Pi Coding Agent
 * Fully compatible with Linux, macOS, and Windows (CMD, PowerShell, Git Bash, WSL).
 *
 * Intercepts:
 *  1. Destructive shell commands (rm, del, rmdir, rd, Remove-Item, git reset/discard, drop db, docker prune, etc.)
 *  2. Direct modifications to sensitive files (write / edit)
 *  3. Reading / inspecting sensitive secret files (.env*, .ssh, private keys, cloud credentials)
 *     via native read tools, shell commands, or runtimes (Python, Node, PHP, Ruby, etc.)
 *
 * Prompts the user with a 4-option menu:
 *   ✓  Allow once
 *   ✗  Block
 *   ✓  Always allow "…" this session
 *   ⚡  YOLO mode — disable ALL guards
 *
 * Non-interactive runs (headless `pi -p`, CI, child agents) have nobody to ask, so
 * they block by default. Opt in with PI_COMMAND_GUARD_NONINTERACTIVE=allow.
 * A command matching several rules gets ONE dialog, not one per rule.
 *
 * Slash commands:
 *   /guard:yolo    — toggle YOLO mode (all guards off)
 *   /guard:reset   — clear session approvals + turn YOLO off
 *   /guard:status  — show current state
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

// ---------------------------------------------------------------------------
// Session-scoped guard state (resets on session reload / new session)
// ---------------------------------------------------------------------------
let yoloMode = false;
const sessionApproved = new Set<string>();

// Headless / CI / subagent runs can't render a dialog. Default: block (fail
// closed). Escape hatch for automation: PI_COMMAND_GUARD_NONINTERACTIVE=allow
const nonInteractiveAllowed = () =>
  /^(1|true|yes|allow)$/i.test(process.env.PI_COMMAND_GUARD_NONINTERACTIVE || "");

// ---------------------------------------------------------------------------
// Helper: compact one-glance summary of a command for the dialog. Keeps the
// first few lines and caps the width so long scripts don't bury the buttons.
// ---------------------------------------------------------------------------
function summarize(command: string, maxLines = 4, maxChars = 220): string {
  const t = (command || "").replace(/\r/g, "").trim();
  if (!t) return "";
  const lines = t.split("\n");
  let shown = lines.slice(0, maxLines).join("\n");
  if (shown.length > maxChars) shown = `${shown.slice(0, maxChars).trimEnd()}…`;
  const hidden = lines.length - maxLines;
  return hidden > 0 ? `${shown}\n… +${hidden} more line${hidden === 1 ? "" : "s"}` : shown;
}

// ---------------------------------------------------------------------------
// Helper: present Block / Allow once / Always allow / YOLO menu via the native
// select dialog (full-width buttons, unlike ctx.ui.custom which pi-web renders
// as a plain text panel).
// Returns true if the operation should be allowed, false if blocked.
// ---------------------------------------------------------------------------
async function guardPrompt(
  ctx: ExtensionContext,
  approveKey: string,
  heading: string,
  details: string[],
  optionLabel: string,        // short label for the "Always allow …" option
): Promise<boolean> {
  if (yoloMode) return true;
  if (sessionApproved.has(approveKey)) return true;
  if (!ctx.hasUI) {
    // Non-interactive → block, unless the operator opted in for automation.
    return nonInteractiveAllowed();
  }

  const title = [`⚠️  ${heading}`, "", ...details.filter(Boolean)].join("\n");
  const options = [
    "✓  Allow once",
    "✗  Block",
    `✓  Always allow ${optionLabel} this session`,
    "⚡  YOLO mode — disable ALL guards",
  ];

  const choice = await ctx.ui.select(title, options);
  if (!choice || choice === options[1]) return false;
  if (choice === options[3]) { yoloMode = true; return true; }
  if (choice === options[2]) { sessionApproved.add(approveKey); return true; }
  return true; // "Allow once"
}

// ---------------------------------------------------------------------------
// Dangerous pattern definitions
// ---------------------------------------------------------------------------

interface DangerousPattern {
  name: string;
  pattern: RegExp;
}

const DANGEROUS_BASH_PATTERNS: DangerousPattern[] = [
  // 1. Scripting runtimes & inline code execution (Linux & Windows: python, py, python3, node, php, perl, ruby)
  {
    name: "Python inline destructive execution",
    pattern: /\b(python[0-9]?|py)\s+(-c|--command)\s+.*(shutil\.(rmtree|move)|os\.(remove|unlink|rmdir|system)|subprocess)/i,
  },
  {
    name: "Node inline destructive execution",
    pattern: /\b(node|bun)\s+(-e|--eval)\s+.*(fs\.(rmSync|rmdirSync|unlinkSync|truncateSync)|child_process)/i,
  },
  {
    name: "Perl / Ruby / PHP inline script execution",
    pattern: /\b(perl|ruby|php)\s+(-e|-r)\s+.*(unlink|rmtree|rm_rf|system|exec|passthru)/i,
  },

  // 2. Encoded / Obfuscated shell execution (PowerShell / Bash / Base64)
  {
    name: "Encoded execution (PowerShell -enc / base64 pipe / eval / iex / process substitution)",
    pattern: /\b((powershell|pwsh).*\s+(-e|-enc|-encodedcommand)\b|base64\s+(-d|--decode)\s*\|\s*(ba)?sh|iex\s*\(|invoke-expression|eval\s+[`"']?\$?\(|\b(bash|sh|zsh|source|\\.)\s+<\(.*\b(curl|wget)\b)/i,
  },

  // 3. Deletion & directory wiping utilities (Unix + Windows CMD + PowerShell)
  {
    name: "Direct file/folder deletion (rm, del, erase, rmdir, rd, Remove-Item)",
    pattern: /\b((?<![\w-])rm\s+(?!--(?:version|help)\b)(-[a-zA-Z]+|--\w+|[^-\s]+)|rmdir(\s+\/s)?|del\s+\S+|(?:^|[;&|]\s*)erase(\s|$)|rd(\s+\/s)?|Remove-Item|ri\s+-force)\b/i,
  },
  {
    name: "Directory sync wipe (rsync --delete / robocopy /mir / /purge)",
    pattern: /\b(rsync\b.*--delete|robocopy\b.*(\/mir|\/purge))\b/i,
  },
  {
    name: "Find / xargs batch deletion",
    pattern: /\bfind\b.*(-delete|-exec\s+(rm|shred))\b/i,
  },
  {
    name: "File clearing / truncation (Clear-Content / truncate / shred / sed wipe / redirect to block device)",
    pattern: /\b(Clear-Content|clc\s|truncate\s+-s\s*0|shred\b|cipher\s+\/w|sed\s+(-i|--in-place)\s+['"]?[^'"\s]*d['"]?(\s|$|;)|(?:^|[\s:;])>\s*\/dev\/(sd[a-z]+|nvme|hd[a-z]|xvd|vd[a-z]|loop|dm-|mmcblk))\b/i,
  },

  // 4. Remote script piping
  {
    name: "Remote script pipe (curl/wget/iwr | sh/bash/python/node/powershell)",
    pattern: /\b(curl|wget|fetch|iwr|invoke-webrequest)\b.*\|\s*(bash|sh|zsh|python[0-9]?|py|node|powershell|pwsh|iex)\b/i,
  },

  // 5. Git destructive operations
  {
    name: "Git discard / hard reset / branch switch (loss of changes)",
    pattern: /\bgit\s+(reset\s+--(hard|merge|keep)|checkout\b|switch\b|restore\b|worktree\s+remove|update-ref\s+-d|reflog\s+delete)/i,
  },
  {
    name: "Git clean (deletes untracked files)",
    pattern: /\bgit\s+clean\s+(-[a-zA-Z]*f|--force)/i,
  },
  {
    name: "Git force push or branch/remote deletion",
    pattern: /\bgit\s+(branch\s+-[dD]|push\s+(?:[^\n]*\s)?(--force\b|-f\b|\+[^\s]+|:[^\s]+)|stash\s+(drop|clear))/i,
  },

  // 6. Databases, Containers, Cloud & Terraform
  {
    name: "Database drop / flush (SQL, Redis, Mongo)",
    pattern: /\b(drop\s+(database|table|schema)|flushall|flushdb|dropdatabase\(\))\b/i,
  },
  {
    name: "Infrastructure / Container destruction (Terraform, Docker prune, K8s delete)",
    pattern: /\b(terraform\s+destroy|docker\s+(system\s+prune|volume\s+prune|image\s+prune|container\s+prune|rm\s+-f|rmi\s+-f)|docker\s+compose\s+down\s+-v|kubectl\s+delete\s+(ns|namespace|all))\b/i,
  },

  // 7. Package managers (NPM / Pip / Yarn / Bun / Cargo)
  {
    name: "NPM publish / force clean / destructive script",
    pattern: /\b(npm|yarn|pnpm|bun)\s+(unpublish|publish|cache\s+clean\s+--force|run\s+(db:drop|clean:all|purge|wipe))\b/i,
  },
  {
    name: "Pip bulk uninstall or system break",
    pattern: /\b(pip|pip3|poetry|uv\s+pip)\s+(uninstall\s+-[yY]|cache\s+purge|install\s+.*--break-system-packages)/i,
  },

  // 8. Privilege escalation & process kill (Unix & Windows)
  {
    name: "Privilege escalation / Permission reset (sudo / chmod / icacls / takeown)",
    pattern: /\b(sudo|su\s+-|chmod\s+(-R\s+)?(\d*[2367]\b|a\+[rwx]+|[augo]\+[rwx]*w)|chown\s+-R|takeown\s+\/f|icacls\s+.*\/grant.*:F)\b/i,
  },
  {
    name: "Force kill process (kill -9/-SIGKILL / pkill / taskkill / Stop-Process)",
    pattern: /\b(kill\s+(-9|-s\s+(KILL|SIGKILL)|-SIGKILL)|killall|pkill|taskkill(\.exe)?\s+\/f|Stop-Process\s+-Force)\b/i,
  },

  // 9. Storage / Low-level formatting (Linux & Windows)
  {
    name: "Disk format / low-level overwrite (format / diskpart / mkfs / dd / wipefs)",
    pattern: /\b(format\s+[a-z]:|diskpart|mkfs|fdisk|dd\s+(if=|of=)|wipefs|dd\s+bs=.*of=)\b/i,
  },

  // 10. Cron / scheduled task destructive ops
  {
    name: "Crontab removal or wipe",
    pattern: /\bcrontab\s+-r\b/i,
  },
];

// Sensitive path signals, shared by the path checks (read/write tools) and the
// command-text checks. `.env` itself is off-limits; committed templates
// (.env.example / .sample / .template / .dist) hold no secrets and stay readable.
const ENV_FILE_RE = /(^|[\/\s"'=<>|;&()@:,])\.env(?!\.(example|sample|template|dist))/i;
const GIT_DIR_RE = /(^|[\/\s"'=])\.git(\/|[\s"']|$)/i;

const SENSITIVE_PATH_PATTERNS = [
  ENV_FILE_RE,
  GIT_DIR_RE,
  /(^|\/)\.ssh(\/|$)/i,
  /\.(pem|key|crt|pfx|p12|kdbx|cert|keystore)$/i,
  /(^|\/)id_(rsa|ed25519|ecdsa|dsa)/i,
  /(service[-_]?account|credentials|client[-_]?secret|token|secret).*\.json$/i,
  /(^|\/)\.(aws|docker|npmrc|pypirc|gem|netrc|rclone)\/?/i,
];

// Keywords across Linux / Windows / PowerShell for reading & inspecting files.
// Word-boundary anchored so "prototype"/"concatenate" don't trip "type"/"cat".
const READ_INSPECT_RE =
  /(?:^|[\s|;&()])(cat|type|head|tail|less|more|grep|rg|awk|sed|strings|od|xxd|base64|tar|unzip|gc|findstr|select-string|get-content)\b|\b(?:open\(|read_text|file_get_contents|readfile|fs\.read|dotenv|fileutils|io\.read)/i;

// Network tools that can carry a secret off the box (curl --data @.env, scp, ssh, git push)
const NETWORK_EXFIL_RE =
  /\b(curl|wget|scp|sftp|ssh|nc|ncat|telnet|rsync|docker\s+push|gh\s+(gist|api)|git\s+push)\b/i;

// Keywords for writing to files via shell (redirection, tee, cp, mv overwrite)
const WRITE_SENSITIVE_RE =
  />>|(?:^|[\s;&|(])(?:>|tee|out-file|set-content|export-)\s|(?:^|[\s;&|])(?:cp|mv|move|copy)\s/i;

function normalizePath(p: string): string {
  return (p || "").replace(/\\/g, "/");
}

function isSensitivePath(targetPath: string): boolean {
  if (!targetPath) return false;
  const normalized = normalizePath(targetPath);
  return SENSITIVE_PATH_PATTERNS.some((p) => p.test(normalized));
}

function containsSensitivePath(text: string): boolean {
  if (!text) return false;
  const normalized = normalizePath(text);
  return (
    ENV_FILE_RE.test(normalized) ||
    GIT_DIR_RE.test(normalized) ||
    /\.ssh/i.test(normalized) ||
    /\.(pem|key|crt|pfx|p12|kdbx|cert|keystore)\b/i.test(normalized) ||
    /id_(rsa|ed25519|ecdsa|dsa)\b/i.test(normalized) ||
    /(service[-_]?account|credentials|client[-_]?secret).*\.json\b/i.test(normalized) ||
    /(^|\/)\.(aws|docker|npmrc|pypirc|gem|netrc|rclone)(\/|$)/i.test(normalized)
  );
}

export default function (pi: ExtensionAPI) {
  // -------------------------------------------------------------------
  // Slash commands
  // -------------------------------------------------------------------

  pi.registerCommand("guard:yolo", {
    description: "Toggle YOLO mode — when ON all command-guard prompts are skipped",
    handler: async (_args, ctx) => {
      yoloMode = !yoloMode;
      const emoji = yoloMode ? "⚡" : "🛡️";
      const status = yoloMode ? "ON — all prompts skipped" : "OFF — prompts active";
      ctx.ui.notify(`${emoji} YOLO mode ${status}`, yoloMode ? "warning" : "info");
    },
  });

  pi.registerCommand("guard:reset", {
    description: "Reset session approvals and disable YOLO mode",
    handler: async (_args, ctx) => {
      sessionApproved.clear();
      yoloMode = false;
      ctx.ui.notify("🛡️  Guard reset — session approvals cleared, YOLO off", "info");
    },
  });

  pi.registerCommand("guard:status", {
    description: "Show current guard state (YOLO, session-approved items)",
    handler: async (_args, ctx) => {
      const lines: string[] = [];
      lines.push(`⚡ YOLO mode: ${yoloMode ? "ON" : "OFF"}`);
      if (sessionApproved.size > 0) {
        lines.push(`✅ Session-approved (${sessionApproved.size}):`);
        for (const key of sessionApproved) lines.push(`   • ${key}`);
      } else {
        lines.push("✅ Session-approved: (none)");
      }
      ctx.ui.notify(lines.join("\n"), "info");
    },
  });

  // -------------------------------------------------------------------
  // Session-scoped state. Every session start (new / resume / fork / reload)
  // clears approvals and turns YOLO off, so "disable ALL guards" can never
  // leak into a session the user did not enable it in.
  // -------------------------------------------------------------------
  pi.on("session_start", () => {
    yoloMode = false;
    sessionApproved.clear();
  });

  // -------------------------------------------------------------------
  // Core tool-call interception
  // -------------------------------------------------------------------

  pi.on("tool_call", async (event, ctx) => {
    // ---------------------------------------------------------------
    // 1. Bash / Shell Tool Calls
    // ---------------------------------------------------------------
    if (event.toolName === "bash") {
      const command = (event.input?.command as string) || "";
      const reasons: string[] = [];

      // A. Destructive/harmful command patterns
      const matchedDestructive = DANGEROUS_BASH_PATTERNS.find((item) => item.pattern.test(command));
      if (matchedDestructive) reasons.push(matchedDestructive.name);

      // B. Reading / writing / exfiltrating sensitive files via shell
      if (containsSensitivePath(command)) {
        const isReadOperation =
          READ_INSPECT_RE.test(command) ||
          NETWORK_EXFIL_RE.test(command) ||
          /\b(python[0-9]?|py|node|bun|php|perl|ruby|powershell|pwsh|bash|sh|cmd)\b/i.test(command);

        const isWriteOperation = WRITE_SENSITIVE_RE.test(command);

        if (isReadOperation || isWriteOperation) {
          reasons.push(isWriteOperation ? "writing to a sensitive file" : "accessing a sensitive file");
        }
      }

      // One dialog per command, even when several rules fire.
      if (reasons.length > 0) {
        const allowed = await guardPrompt(
          ctx,
          `bash:${reasons.join(" + ")}`,
          reasons[0],
          [reasons.length > 1 ? `also: ${reasons.slice(1).join(" + ")}` : "", summarize(command)],
          `"${reasons.join('" + "')}"`,
        );

        if (!allowed) {
          ctx.ui.notify("Command blocked", "warning");
          return {
            block: true,
            reason: `User rejected: "${command}" (${reasons.join(" + ")})`,
          };
        }
      }
    }

    // ---------------------------------------------------------------
    // 2. Native Read Tools
    // ---------------------------------------------------------------
    if (event.toolName === "read" || event.toolName === "read_symbol" || event.toolName === "read_enclosing") {
      const targetPath = (event.input?.path as string) || "";
      if (isSensitivePath(targetPath)) {
        const allowed = await guardPrompt(
          ctx,
          `file-read:${targetPath}`,
          "Read sensitive file",
          [targetPath],
          `reading "${targetPath}"`,
        );

        if (!allowed) {
          ctx.ui.notify(`Read of ${targetPath} denied`, "warning");
          return {
            block: true,
            reason: `User denied read of sensitive file: "${targetPath}"`,
          };
        }
      }
    }

    // ---------------------------------------------------------------
    // 3. Direct File Modifications (write / edit)
    // ---------------------------------------------------------------
    if (event.toolName === "write" || event.toolName === "edit") {
      const targetPath = (event.input?.path as string) || "";
      if (isSensitivePath(targetPath)) {
        const allowed = await guardPrompt(
          ctx,
          `file-write:${targetPath}`,
          "Modify sensitive file",
          [targetPath],
          `modifying "${targetPath}"`,
        );

        if (!allowed) {
          ctx.ui.notify(`Modification of ${targetPath} cancelled`, "warning");
          return {
            block: true,
            reason: `User denied modification of sensitive path: "${targetPath}"`,
          };
        }
      }
    }

    return undefined;
  });
}
