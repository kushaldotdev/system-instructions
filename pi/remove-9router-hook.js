#!/usr/bin/env node
// ============================================================================
// remove-9router-hook.js
// ----------------------------------------------------------------------------
// Removes the 9Router "always-on" hook from a machine so Pi stops calling the
// network + schema sanitizer on every launch.
//
// TWO jobs:
//
//   A) Legacy always-on hook (the old 9router-discovery.ts):
//      The hook is made of TWO pieces, and BOTH must go:
//        1. The extension file          ~/.pi/agent/extensions/9router-discovery.ts
//        2. The settings entry          "extensions/9router-discovery.ts" in the
//                                       `packages` array of
//                                       ~/.pi/agent/settings.json
//                                       (and .pi/settings.json if project-scoped)
//
//   B) Current on-demand 9router-sync.ts:
//      Strips ANY `pi.on(...)` lifecycle-hook registration from
//      ~/.pi/agent/extensions/9router-sync.ts, so nothing custom runs at Pi
//      launch. The /9router-sync slash command (registerCommand) is kept —
//      that is on-demand only and does not run at launch.
//
// Usage:
//   node pi/remove-9router-hook.js
//
// Cross-platform: works on Windows (PowerShell/cmd), Linux, and WSL.
// Safe to re-run: does nothing if the hook is already gone.
// ============================================================================

const fs = require("fs");
const path = require("path");
const os = require("os");

// The exact identity of the legacy hook we are removing.
const HOOK_SOURCE = "extensions/9router-discovery.ts";
const HOOK_FILENAME = "9router-discovery.ts";

// The current on-demand extension (hooks stripped in-place, command kept).
const SYNC_FILENAME = "9router-sync.ts";

// Candidate locations where the file + settings can live.
const GLOBAL_EXT_DIR = path.join(os.homedir(), ".pi", "agent", "extensions");
const GLOBAL_SETTINGS = path.join(
	os.homedir(),
	".pi",
	"agent",
	"settings.json",
);
const PROJECT_SETTINGS = path.join(process.cwd(), ".pi", "settings.json");

function log(msg) {
	console.log(`[remove-9router-hook] ${msg}`);
}

function warn(msg) {
	console.warn(`[remove-9router-hook] WARN: ${msg}`);
}

function removeEntryFromPackages(packages) {
	if (!Array.isArray(packages)) return { packages, removed: false };
	let removed = false;
	const filtered = packages.filter((p) => {
		const key = typeof p === "string" ? p : p?.source;
		if (key === HOOK_SOURCE) {
			removed = true;
			return false;
		}
		return true;
	});
	return { packages: filtered, removed };
}

// Rewrite settings.json, dropping the hook entry from `packages`.
// Preserves every other key exactly as it was.
function scrubSettings(settingsPath) {
	if (!fs.existsSync(settingsPath)) {
		log(`No settings file at ${settingsPath} — nothing to scrub.`);
		return false;
	}

	let raw;
	try {
		raw = fs.readFileSync(settingsPath, "utf-8");
	} catch (err) {
		warn(`Could not read ${settingsPath}: ${err.message}`);
		return false;
	}

	let settings;
	try {
		settings = JSON.parse(raw);
	} catch (err) {
		warn(
			`Could not parse ${settingsPath} (${err.message}). Left untouched — edit it manually.`,
		);
		return false;
	}

	const { packages, removed } = removeEntryFromPackages(settings.packages);
	if (!removed) {
		log(`No '${HOOK_SOURCE}' entry in ${settingsPath} — nothing to remove.`);
		return false;
	}

	settings.packages = packages;

	// Back up before mutating (paranoia; keeps the file restorable).
	const backup = `${settingsPath}.bak-9router-${Date.now()}`;
	try {
		fs.writeFileSync(backup, raw, "utf-8");
	} catch (err) {
		warn(`Could not write backup ${backup}: ${err.message}`);
	}

	try {
		fs.writeFileSync(
			settingsPath,
			JSON.stringify(settings, null, 2) + "\n",
			"utf-8",
		);
		log(`Removed '${HOOK_SOURCE}' from ${settingsPath}`);
		log(`Backup saved to ${backup}`);
		return true;
	} catch (err) {
		warn(`Could not write ${settingsPath}: ${err.message}`);
		return false;
	}
}

// Delete the legacy extension file itself.
function deleteExtensionFile() {
	const file = path.join(GLOBAL_EXT_DIR, HOOK_FILENAME);
	if (!fs.existsSync(file)) {
		log(`No extension file at ${file} — nothing to delete.`);
		return false;
	}
	try {
		fs.unlinkSync(file);
		log(`Deleted ${file}`);
		return true;
	} catch (err) {
		warn(`Could not delete ${file}: ${err.message}`);
		return false;
	}
}

// Strip any `pi.on(...)` lifecycle-hook registrations from the current
// 9router-sync.ts so nothing runs at Pi launch. The on-demand slash command
// (pi.registerCommand) is preserved — it never runs at launch.
// This is line-based and conservative: it removes `pi.on(...)` blocks that span
// balanced braces/parens, keeping every other line untouched. A backup of the
// original file is written first.
function stripHooksFromSyncExtension() {
	const file = path.join(GLOBAL_EXT_DIR, SYNC_FILENAME);
	if (!fs.existsSync(file)) {
		log(`No extension file at ${file} — nothing to strip.`);
		return false;
	}

	const raw = fs.readFileSync(file, "utf-8");
	const lines = raw.split(/\r?\n/);
	const out = [];
	let removed = 0;

	for (let i = 0; i < lines.length; i++) {
		const line = lines[i];
		const trimmed = line.trim();
		// Only consider actual `pi.on(` calls (not comments / strings containing it).
		if (/^pi\.on\(/.test(trimmed)) {
			// Consume the full statement: balanced parens, then optional `;`.
			let depth = 0;
			const start = i;
			let j = i;
			let consumed = "";
			let done = false;
			for (; j < lines.length; j++) {
				consumed += lines[j] + "\n";
				for (const ch of lines[j]) {
					if (ch === "(") depth++;
					else if (ch === ")") depth--;
				}
				// Heuristic: statement ends when parens are balanced and the line ends
				// with `)` or `;` (possibly after whitespace).
				if (depth <= 0 && /[);]\s*$/.test(lines[j])) {
					done = true;
					break;
				}
			}
			if (done) {
				removed++;
				log(`Removed pi.on(...) hook starting at line ${start + 1} of ${file}`);
				i = j; // skip the whole statement
				continue;
			}
		}
		out.push(line);
	}

	if (removed === 0) {
		log(`No pi.on(...) hooks found in ${file} — nothing to strip.`);
		return false;
	}

	const backup = `${file}.bak-9router-${Date.now()}`;
	try {
		fs.writeFileSync(backup, raw, "utf-8");
		log(`Backup saved to ${backup}`);
	} catch (err) {
		warn(`Could not write backup ${backup}: ${err.message}`);
	}

	try {
		fs.writeFileSync(file, out.join("\n"), "utf-8");
		log(`Stripped ${removed} pi.on(...) hook(s) from ${file}`);
		return true;
	} catch (err) {
		warn(`Could not write ${file}: ${err.message}`);
		return false;
	}
}

function main() {
	console.log("=============================================");
	console.log("  Remove 9Router launch-time hooks            ");
	console.log("=============================================");

	deleteExtensionFile();
	scrubSettings(GLOBAL_SETTINGS);
	scrubSettings(PROJECT_SETTINGS);
	stripHooksFromSyncExtension();

	console.log("---------------------------------------------");
	log("Done. Restart Pi (or use /reload) for the change to take effect.");
	console.log("=============================================");
}

main();
