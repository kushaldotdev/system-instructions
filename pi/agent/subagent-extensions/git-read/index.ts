import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

// Read-only subcommands. Commands that can mutate (branch, tag, remote,
// config, stash, worktree, reflog, submodule) have extra argument guards below.
const READ_ONLY_SUBCOMMANDS = new Set([
  "diff",
  "log",
  "show",
  "status",
  "branch",
  "ls-tree",
  "rev-parse",
  "cat-file",
  "ls-files",
  "ls-remote",
  "rev-list",
  "merge-base",
  "name-rev",
  "describe",
  "blame",
  "annotate",
  "shortlog",
  "for-each-ref",
  "count-objects",
  "verify-commit",
  "verify-tag",
  "check-ignore",
  "check-attr",
  "symbolic-ref",
  "whatchanged",
  "cherry",
  "grep",
  "fsck",
  "version",
  "remote",
  "tag",
  "config",
  "stash",
  "worktree",
  "reflog",
  "submodule",
]);

// For ambiguous commands: the first argument must be one of these read-only
// actions, or the command must be bare (which lists by default).
const READ_ONLY_ACTIONS: Record<string, string[]> = {
  remote: ["-v", "--verbose", "show", "get-url"],
  config: [
    "-l",
    "--list",
    "--get",
    "--get-all",
    "--get-regexp",
    "--get-urlmatch",
    "--show-origin",
    "--show-scope",
  ],
  stash: ["list", "show"],
  worktree: ["list"],
  reflog: ["show", "exists"],
  submodule: ["status", "summary"],
  tag: [
    "-l",
    "--list",
    "-n",
    "-i",
    "--ignore-case",
    "--format",
    "--sort",
    "--contains",
    "--merged",
    "--no-merged",
    "--points-at",
    "--column",
  ],
};

// Flags that take a value: the token after them is data, not a branch name.
const BRANCH_VALUE_FLAGS = new Set([
  "--contains",
  "--merged",
  "--no-merged",
  "--points-at",
  "--sort",
  "--format",
]);

// branch defaults to listing, but flag-based forms can mutate.
const BRANCH_WRITE_FLAGS = [
  /^-d$/,
  /^-D$/,
  /^-m$/,
  /^-M$/,
  /^-c$/,
  /^-C$/,
  /^-f$/,
  /^--delete$/,
  /^--move$/,
  /^--copy$/,
  /^--edit-description$/,
  /^--set-upstream-to/,
  /^--unset-upstream$/,
  /^--create-reflog$/,
  /^--force$/,
  /^--track/,
  /^--no-track$/,
];

// Flags that write to disk, invoke pagers/hooks, or execute external programs.
const FORBIDDEN_FLAG_PATTERNS = [
  /--output\b/,
  /--output=/,
  /^-o$/,
  /--paginate\b/,
  /--no-pager\b/,
  /--ext-diff\b/,
  /--textconv\b/,
  /^-c$/,
  /--config-env/,
  /--exec-path/,
  /--upload-pack/,
  /--receive-pack/,
  /--exec=?\S*$/,
  /^--lost-found$/,
  /^-O/,
  /^--open-files-in-pager/,
];

function parseCommandTokens(input: string): string[] {
  const trimmed = input.trim();
  // Strip leading "git " if caller included it
  const clean = trimmed.startsWith("git ") ? trimmed.slice(4).trim() : trimmed;

  // Split by whitespace respecting quotes
  const matches = clean.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g);
  if (!matches || matches.length === 0) return [];
  return matches.map((t) => t.replace(/^["']|["']$/g, ""));
}

function deny(text: string) {
  return { isError: true, content: [{ type: "text" as const, text }] };
}

export default function gitReadExtension(api: ExtensionAPI) {
  api.registerTool({
    name: "git_read",
    description:
      "Read-only git inspector. Supports logs, branches, diffs, history, refs, trees, blobs, blame and more. Examples: 'log -n 5 --oneline', 'branch -a', 'diff --cached', 'show HEAD', 'ls-tree -r HEAD', 'rev-parse HEAD', 'cat-file -p HEAD:file', 'blame src/main.ts', 'remote -v', 'stash list'. Mutating commands are rejected.",
    parameters: {
      type: "object",
      properties: {
        command: {
          type: "string",
          description:
            "Git command with flags, without the leading 'git' (e.g. 'log -n 5 --oneline', 'branch -a', 'ls-tree -r HEAD').",
        },
      },
      required: ["command"],
    },
    execute: async (_toolCallId, params, ctx) => {
      const commandStr = (params.command as string | undefined)?.trim() ?? "";
      if (!commandStr) {
        return deny("Error: No command provided. Pass a read-only git command, e.g. 'log -n 5 --oneline'.");
      }

      const tokens = parseCommandTokens(commandStr);
      if (tokens.length === 0) {
        return deny("Error: Empty command string.");
      }

      const subcommand = tokens[0].toLowerCase();
      if (!READ_ONLY_SUBCOMMANDS.has(subcommand)) {
        return deny(
          `Error: 'git ${subcommand}' is not permitted. Only read-only git commands are allowed (log, branch, diff, show, ls-tree, rev-parse, cat-file, blame, ...). Mutating commands are rejected.`,
        );
      }

      const args = tokens.slice(1);

      // Reject flags that write or execute external programs.
      for (const token of args) {
        for (const pattern of FORBIDDEN_FLAG_PATTERNS) {
          if (pattern.test(token)) {
            return deny(`Error: Flag '${token}' is not allowed in read-only mode.`);
          }
        }
      }

      // branch: allow listing/showing, block mutation flags.
      if (subcommand === "branch") {
        if (args.some((t) => BRANCH_WRITE_FLAGS.some((p) => p.test(t)))) {
          return deny("Error: 'git branch' with mutation flags is not allowed in read-only mode.");
        }
        // A bare positional ('git branch <name> [<start>]') CREATES a branch, so
        // positionals are only allowed as the value of an allowlisted flag.
        let expectValue = false;
        const branchPositionals: string[] = [];
        for (const token of args) {
          if (expectValue) {
            expectValue = false;
            continue;
          }
          if (token.startsWith("-")) {
            if (BRANCH_VALUE_FLAGS.has(token)) expectValue = true;
            continue;
          }
          branchPositionals.push(token);
        }
        if (branchPositionals.length > 0) {
          return deny(
            `Error: positional argument '${branchPositionals[0]}' is not allowed with 'git branch' (it would create or modify a branch). Use -a, -r, -v, --list, --contains <rev>, --merged <rev>, --points-at <rev>.`,
          );
        }
      }

      // Ambiguous commands: first arg must be a known read-only action.
      const allowedActions = READ_ONLY_ACTIONS[subcommand];
      if (allowedActions && args.length > 0 && !allowedActions.includes(args[0])) {
        return deny(
          `Error: 'git ${subcommand} ${args[0]}' is not a permitted read-only form. Allowed: ${allowedActions.join(", ")}.`,
        );
      }

      const cwd = ctx.cwd;
      const gitArgs = ["--no-pager", ...tokens];

      try {
        const { stdout, stderr } = await execFileAsync("git", gitArgs, {
          cwd,
          maxBuffer: 10 * 1024 * 1024, // 10MB limit
        });

        const output = (stdout || stderr || "(empty output)").trimEnd();
        return {
          content: [{ type: "text", text: output }],
        };
      } catch (err: unknown) {
        const error = err as { code?: number; stdout?: string; stderr?: string; message?: string };
        const message = error.stderr?.trim() || error.stdout?.trim() || error.message || String(err);
        return deny(`git ${subcommand} failed:\n${message}`);
      }
    },
  });
}
