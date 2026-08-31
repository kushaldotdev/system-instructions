/**
 * Pi Web Subagents Bridge Extension
 * 
 * Automatically bridges async (and sync) subagents spawned by `pi-subagents`
 * into the format expected by `@agegr/pi-web`.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";

function formatSessionTimestamp(dateStr?: string): string {
  const d = dateStr ? new Date(dateStr) : new Date();
  return d.toISOString().replace(/[:.]/g, "-");
}

function syncSubagentFile(
  sourcePath: string,
  parentSessionPath: string,
  parentSessionId: string
) {
  try {
    if (!fs.existsSync(sourcePath)) return;

    const content = fs.readFileSync(sourcePath, "utf8");
    const lines = content.split("\n").filter((l) => l.trim().length > 0);
    if (lines.length === 0) return;

    const firstEntry = JSON.parse(lines[0]);
    if (firstEntry.type !== "session" || !firstEntry.id) return;

    const childSessionId = firstEntry.id;
    const timestampStr = firstEntry.timestamp || new Date().toISOString();
    const formattedTs = formatSessionTimestamp(timestampStr);
    const sessionsDir = path.dirname(parentSessionPath);
    const targetFileName = `${formattedTs}_${childSessionId}.jsonl`;
    const targetPath = path.join(sessionsDir, targetFileName);

    // Extract first user message for task description
    let taskText = "Subagent task";
    for (const line of lines) {
      try {
        const entry = JSON.parse(line);
        if (entry.type === "message" && entry.message?.role === "user") {
          const c = entry.message.content;
          if (typeof c === "string") taskText = c;
          else if (Array.isArray(c)) {
            for (const part of c) {
              if (part.type === "text" && part.text) taskText = part.text;
            }
          }
          break;
        }
      } catch {}
    }

    const description = taskText.split("\n")[0].slice(0, 80);

    // Extract last assistant message for result
    let hasResult = false;
    let finalResult = "";
    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        const entry = JSON.parse(lines[i]);
        if (entry.customType === "pi-web:subagent-result") {
          hasResult = true;
          break;
        }
        if (!finalResult && entry.type === "message" && entry.message?.role === "assistant") {
          const c = entry.message.content;
          if (typeof c === "string") finalResult = c;
          else if (Array.isArray(c)) {
            for (const part of c) {
              if (part.type === "text" && part.text) finalResult = part.text;
            }
          }
        }
      } catch {}
    }

    // Build clean session lines with a continuous unbroken tree DAG
    const cleanLines: string[] = [];

    // Header with parentSession linked
    const header = {
      ...firstEntry,
      parentSession: parentSessionPath,
    };
    cleanLines.push(JSON.stringify(header));

    const metaId = "subagent-meta-" + childSessionId.slice(0, 8);
    const subagentMeta = {
      type: "custom",
      customType: "pi-web:subagent",
      data: {
        version: 1,
        parentSessionId,
        parentSessionPath,
        profile: "worker",
        description,
        task: taskText.slice(0, 500),
        runInBackground: true,
        createdAt: timestampStr,
      },
      id: metaId,
      parentId: null,
      timestamp: timestampStr,
    };
    cleanLines.push(JSON.stringify(subagentMeta));

    let lastId: string | null = metaId;
    let isFirstChild = true;

    // Copy original messages & entries, chaining parentId properly
    for (let i = 1; i < lines.length; i++) {
      try {
        const entry = JSON.parse(lines[i]);
        if (entry.type === "session") continue;
        if (entry.customType === "pi-web:subagent") continue;
        if (entry.customType === "pi-web:subagent-result") {
          hasResult = true;
        }

        if (isFirstChild) {
          if (entry.parentId === null || entry.parentId === undefined) {
            entry.parentId = metaId;
          }
          isFirstChild = false;
        }

        if (entry.id) {
          lastId = entry.id;
        }
        cleanLines.push(JSON.stringify(entry));
      } catch {}
    }

    // Append subagent result if complete, chained to lastId
    if (!hasResult && finalResult) {
      const resultEntry = {
        type: "custom",
        customType: "pi-web:subagent-result",
        data: {
          status: "completed",
          completedAt: new Date().toISOString(),
          result: finalResult.slice(0, 500),
        },
        id: "subagent-res-" + childSessionId.slice(0, 8),
        parentId: lastId,
        timestamp: new Date().toISOString(),
      };
      cleanLines.push(JSON.stringify(resultEntry));
    }

    // Write atomic clean file
    const outputContent = cleanLines.join("\n") + "\n";
    fs.writeFileSync(targetPath, outputContent, "utf8");

  } catch (err) {
    // ignore
  }
}

function scanAndSyncSubagents(parentSessionPath: string, parentSessionId: string) {
  try {
    if (!parentSessionPath || !fs.existsSync(parentSessionPath)) return;

    const baseName = path.basename(parentSessionPath, ".jsonl");
    const sessionsDir = path.dirname(parentSessionPath);
    const subagentsRootDir = path.join(sessionsDir, baseName);

    if (!fs.existsSync(subagentsRootDir)) return;

    const runDirs = fs.readdirSync(subagentsRootDir, { withFileTypes: true });
    for (const runDir of runDirs) {
      if (!runDir.isDirectory()) continue;
      const runDirPath = path.join(subagentsRootDir, runDir.name);

      const candidatePaths = [
        path.join(runDirPath, "run-0", "session.jsonl"),
        path.join(runDirPath, "session.jsonl"),
      ];

      for (const src of candidatePaths) {
        if (fs.existsSync(src)) {
          syncSubagentFile(src, parentSessionPath, parentSessionId);
        }
      }
    }
  } catch {}
}

export default function piWebSubagentBridge(pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    try {
      const parentId = ctx.sessionManager.getSessionId();
      const parentFile = ctx.sessionManager.getSessionFile();
      if (parentFile && parentId) {
        scanAndSyncSubagents(parentFile, parentId);
      }
    } catch {}
  });

  pi.on("tool_result", async (event, ctx) => {
    try {
      if (event.toolName !== "subagent") return;
      const parentFile = ctx.sessionManager.getSessionFile();
      const parentId = ctx.sessionManager.getSessionId();
      if (parentFile && parentId) {
        setTimeout(() => scanAndSyncSubagents(parentFile, parentId), 500);
        setTimeout(() => scanAndSyncSubagents(parentFile, parentId), 2000);
      }
    } catch {}
  });

  pi.on("agent_end", async (_event, ctx) => {
    try {
      const parentFile = ctx.sessionManager.getSessionFile();
      const parentId = ctx.sessionManager.getSessionId();
      if (parentFile && parentId) {
        scanAndSyncSubagents(parentFile, parentId);
      }
    } catch {}
  });
}
