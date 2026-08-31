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
 *   ✗  Block
 *   ✓  Allow once
 *   ✓  Always allow "…" this session
 *   ⚡  YOLO mode — disable ALL guards
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

// ---------------------------------------------------------------------------
// Helper: present Block / Allow once / Always allow / YOLO menu
// Returns true if the operation should be allowed, false if blocked.
// ---------------------------------------------------------------------------
async function guardPrompt(
  ctx: ExtensionContext,
  approveKey: string,
  title: string,
  optionLabel: string,   // short label for the "Always allow …" option
): Promise<boolean> {
  if (yoloMode) return true;
  if (sessionApproved.has(approveKey)) return true;
  if (!ctx.hasUI) return false;              // non-interactive → block

  const choice = await ctx.ui.select(
    `⚠️  Guard  —  ${title}`,
    [
      "✓  Allow once",
      "✗  Block",
      `✓  Always allow ${optionLabel} this session`,
      "⚡  YOLO mode — disable ALL guards",
    ],
  );

  if (!choice || choice.startsWith("✗")) return false;
  if (choice.startsWith("⚡")) { yoloMode = true; return true; }
  if (choice.includes("Always allow")) { sessionApproved.add(approveKey); return true; }
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
    pattern: /\b(rm\s+(-[a-zA-Z]*[rf]|--recursive|--force)|rmdir(\s+\/s)?|del(\s+\/[fqsa]+|\s+-[a-zA-Z]+)*|erase|rd(\s+\/s)?|Remove-Item|ri\s+-force)\b/i,
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
    pattern: /\b(Clear-Content|clc\s|truncate\s+-s\s*0|shred\b|cipher\s+\/w|sed\s+(-i|--in-place)\s+.*[0-9$,]*d|(?:^|[\s:;])>\s*\/dev\/(sd[a-z]+|nvme|hd[a-z]|xvd|vd[a-z]|loop|dm-|mmcblk))\b/i,
  },

  // 4. Remote script piping
  {
    name: "Remote script pipe (curl/wget/iwr | sh/bash/python/node/powershell)",
    pattern: /\b(curl|wget|fetch|iwr|invoke-webrequest)\b.*\|\s*(bash|sh|zsh|python[0-9]?|py|node|powershell|pwsh|iex)\b/i,
  },

  // 5. Git destructive operations
  {
    name: "Git discard / hard reset (loss of changes)",
    pattern: /\bgit\s+(reset\s+--(hard|merge|keep)|checkout\s+(\.|--\s+\S+)|restore(\s+\.|\s+--staged\s+\.))/i,
  },
  {
    name: "Git clean (deletes untracked files)",
    pattern: /\bgit\s+clean\s+(-[a-zA-Z]*f|--force)/i,
  },
  {
    name: "Git force push or branch/remote deletion",
    pattern: /\bgit\s+(branch\s+-[dD]|push\s+.*(--force|-f|\+refs\/|:[^\s]+)|stash\s+(drop|clear))/i,
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
    pattern: /\b(sudo|su\s+-|chmod\s+(-R\s+)?([0-7]*[^1-6]7[0-7]*|a\+rwx|[ugo]\+w)|chown\s+-R|takeown\s+\/f|icacls\s+.*\/grant.*:F)\b/i,
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

// Sensitive file patterns: .env* files, private keys, SSH keys, credentials, cloud configs
const SENSITIVE_PATH_PATTERNS = [
  /(^|\/)\.env/i,
  /(^|\/)\.git(\/|$)/i,
  /(^|\/)\.ssh(\/|$)/i,
  /\.(pem|key|crt|pfx|p12|kdbx|cert|keystore)$/i,
  /(^|\/)id_(rsa|ed25519|ecdsa|dsa)/i,
  /(service[-_]?account|credentials|client[-_]?secret|token|secret).*\.json$/i,
  /(^|\/)\.(aws|docker|npmrc|pypirc|gem|netrc|rclone)\/?/i,
];

// Keywords across Linux / Windows / PowerShell for reading & inspecting files
const READ_INSPECT_KEYWORDS = [
  "cat", "type", "head", "tail", "less", "more", "grep", "rg", "strings",
  "get-content", "gc", "findstr", "select-string",
  "open(", "read_text", "file_get_contents", "readfile",
  "fs.read", "require('dotenv')", "dotenv", "fileutils", "io.read"
];

// Keywords for writing to files via shell (redirection, tee, cp, mv overwrite)
const WRITE_SENSITIVE_KEYWORDS = [
  ">>", ">", "tee", "cp ", "mv ", "move ", "copy ",
  "out-file", "set-content", "export-"
];

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
    /\.env/i.test(normalized) ||
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
  // Core tool-call interception
  // -------------------------------------------------------------------

  pi.on("tool_call", async (event, ctx) => {
    // ---------------------------------------------------------------
    // 1. Bash / Shell Tool Calls
    // ---------------------------------------------------------------
    if (event.toolName === "bash") {
      const command = (event.input?.command as string) || "";

      // A. Destructive/harmful command patterns
      const matchedDestructive = DANGEROUS_BASH_PATTERNS.find((item) => item.pattern.test(command));
      if (matchedDestructive) {
        const allowed = await guardPrompt(
          ctx,
          `pattern:${matchedDestructive.name}`,
          `${matchedDestructive.name}\n\n  ${command}`,
          `"${matchedDestructive.name}"`,
        );

        if (!allowed) {
          ctx.ui.notify("Command blocked", "warning");
          return {
            block: true,
            reason: `User rejected: "${command}" (${matchedDestructive.name})`,
          };
        }
      }

      // B. Reading / writing sensitive files via shell
      if (containsSensitivePath(command)) {
        const lowerCmd = command.toLowerCase();
        const isReadOperation =
          READ_INSPECT_KEYWORDS.some((kw) => lowerCmd.includes(kw)) ||
          /\b(python[0-9]?|py|node|bun|php|perl|ruby|powershell|pwsh|bash|sh|cmd)\b/i.test(command);

        const isWriteOperation =
          WRITE_SENSITIVE_KEYWORDS.some((kw) => lowerCmd.includes(kw));

        if (isReadOperation || isWriteOperation) {
          const direction = isWriteOperation ? "writing to" : "accessing";
          const allowed = await guardPrompt(
            ctx,
            `sensitive-bash:${direction}`,
            `${isWriteOperation ? "Write" : "Access"} to sensitive file\n\n  ${command}`,
            `"${direction} sensitive files"`,
          );

          if (!allowed) {
            ctx.ui.notify("Sensitive file access blocked", "warning");
            return {
              block: true,
              reason: `User blocked ${direction} sensitive file: "${command}"`,
            };
          }
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
          `Read sensitive file\n\n  ${targetPath}`,
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
          `Modify sensitive file\n\n  ${targetPath}`,
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
