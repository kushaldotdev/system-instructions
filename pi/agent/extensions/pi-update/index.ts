/**
 * pi-update — slash command to update pi itself and all extensions/packages
 * in one go, without leaving the session.
 *
 *   /update            update pi + all packages (pi update --all)
 *   /update pi         update pi only (pi update --self)
 *   /update ext        update extensions only (pi update --extensions)
 *
 * UX:
 *  - Confirms first, then runs `pi update` as a child process.
 *  - While running: a widget above the input shows elapsed time + the latest
 *    output lines. npm is run at `http` loglevel (via npm_config_loglevel) so
 *    per-package install/fetch progress streams into the widget live.
 *  - On completion: an ACCURATE summary of what actually changed — pi version
 *    bump and/or added/changed/removed packages — and "already up to date"
 *    only when nothing changed. `pi update --all` always prints
 *    "pi is already up to date" when pi itself is current even when packages
 *    were updated, so a naive grep of that string gave false "nothing to do"
 *    messages. This parses the pieces separately.
 *  - Windows: npm installs `pi` as `pi.cmd`/`pi.ps1` shims. Plain
 *    spawn("pi") fails with ENOENT and even spawn("pi.cmd") fails with EINVAL
 *    unless run through a shell, so the binary is resolved with `where` and
 *    executed via cmd.exe (shell:true).
 *  - No log files, no follow-up prompts.
 */

import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const IS_WIN = process.platform === "win32";

/** Run npm at `http` loglevel so its per-package fetch/install lines stream into the widget. */
const UPDATE_ENV = { ...process.env, npm_config_loglevel: "http", npm_config_color: "false" };

/** Strip ANSI escape sequences + CR noise from an output line for widget display. */
function cleanLine(line: string): string {
	return line.replace(/\u001b\[[0-9;]*m/g, "").replace(/[\r\n]+/g, "").trim();
}

function getAgentDir(): string {
	const custom = process.env.PI_CODING_AGENT_DIR;
	if (custom) return custom;
	if (process.env.XDG_CONFIG_HOME) return path.join(process.env.XDG_CONFIG_HOME, "pi");
	const home = os.homedir();
	const agentPath = path.join(home, ".pi", "agent");
	if (fs.existsSync(agentPath)) return agentPath;
	return path.join(home, ".pi");
}

/**
 * Resolve the pi CLI binary.
 * - Windows: npm installs `pi.cmd` in AppData\Roaming\npm. `where pi` finds it;
 *   a .cmd/.bat shim must be executed through a shell (see handler).
 * - POSIX: `which pi`, then the agent-dir layout, then bare "pi".
 */
function resolvePiBinary(): string {
	if (IS_WIN) {
		try {
			const out = execFileSync("where", ["pi"], { encoding: "utf8" });
			const hits = out.split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean);
			const shim = hits.find((h) => /\.(cmd|bat)$/i.test(h))
				?? hits.find((h) => /\.exe$/i.test(h))
				?? hits[0];
			if (shim) return shim;
		} catch {
			/* not on PATH — fall through to bare name */
		}
		return "pi"; // cmd.exe resolves `pi` → `pi.cmd` via PATHEXT
	}
	try {
		const fromPath = execFileSync("which", ["pi"], { encoding: "utf8" }).trim();
		if (fromPath) return fromPath;
	} catch {
		/* fall through */
	}
	const agentDir = getAgentDir();
	const candidates = [
		path.join(agentDir, "bin", "pi"),
		path.join(agentDir, "agent", "bin", "pi"),
		path.join(os.homedir(), ".pi", "bin", "pi"),
		path.join(os.homedir(), ".pi", "agent", "bin", "pi"),
	];
	for (const c of candidates) {
		try { if (fs.existsSync(c)) return c; } catch { /* ignore */ }
	}
	return "pi";
}

function getPiVersion(bin: string): string | null {
	try {
		const out = execFileSync(bin, ["--version"], { encoding: "utf8", timeout: 5000 }).trim();
		const m = out.match(/\bv?(\d+\.\d+\.\d+(?:-[\w.]+)?)/);
		return m ? m[1] : (out || null);
	} catch {
		return null;
	}
}

function getConfiguredPackageNames(agentDir: string, cwd: string): Set<string> {
	const configured = new Set<string>();
	const settingsFiles = [
		path.join(agentDir, "settings.json"),
		path.join(os.homedir(), ".pi", "agent", "settings.json"),
		path.join(os.homedir(), ".pi", "settings.json"),
		path.join(cwd, ".pi", "settings.json"),
	];
	for (const sf of settingsFiles) {
		try {
			if (!fs.existsSync(sf)) continue;
			const data = JSON.parse(fs.readFileSync(sf, "utf8"));
			if (Array.isArray(data.packages)) {
				for (const pkg of data.packages) {
					const src = typeof pkg === "string" ? pkg : (pkg && typeof pkg === "object" ? pkg.source : "");
					if (typeof src === "string" && src) {
						let clean = src.trim();
						if (clean.startsWith("npm:")) clean = clean.slice(4);
						else if (clean.startsWith("git:")) clean = clean.slice(4);
						if (clean.startsWith("@")) {
							const atIdx = clean.indexOf("@", 1);
							if (atIdx !== -1) clean = clean.slice(0, atIdx);
						} else {
							const atIdx = clean.indexOf("@");
							if (atIdx !== -1) clean = clean.slice(0, atIdx);
						}
						const hashIdx = clean.indexOf("#");
						if (hashIdx !== -1) clean = clean.slice(0, hashIdx);
						configured.add(clean);
					}
				}
			}
		} catch {
			/* ignore */
		}
	}
	return configured;
}

function getInstalledPackagesSnapshot(agentDir: string, cwd: string): Map<string, string> {
	const map = new Map<string, string>();
	const npmRoots = [
		path.join(agentDir, "npm", "node_modules"),
		path.join(os.homedir(), ".pi", "agent", "npm", "node_modules"),
		path.join(os.homedir(), ".pi", "npm", "node_modules"),
		path.join(cwd, ".pi", "npm", "node_modules"),
	];

	for (const root of npmRoots) {
		if (!fs.existsSync(root)) continue;
		try {
			const entries = fs.readdirSync(root, { withFileTypes: true });
			for (const entry of entries) {
				if (entry.isDirectory()) {
					if (entry.name.startsWith("@")) {
						const scopeDir = path.join(root, entry.name);
						try {
							const scopedEntries = fs.readdirSync(scopeDir, { withFileTypes: true });
							for (const sub of scopedEntries) {
								if (sub.isDirectory()) {
									const pkgJsonPath = path.join(scopeDir, sub.name, "package.json");
									if (fs.existsSync(pkgJsonPath)) {
										try {
											const data = JSON.parse(fs.readFileSync(pkgJsonPath, "utf8"));
											if (data.name && data.version) {
												map.set(data.name, data.version);
											}
										} catch {
											/* ignore */
										}
									}
								}
							}
						} catch {
							/* ignore */
						}
					} else {
						const pkgJsonPath = path.join(root, entry.name, "package.json");
						if (fs.existsSync(pkgJsonPath)) {
							try {
								const data = JSON.parse(fs.readFileSync(pkgJsonPath, "utf8"));
								if (data.name && data.version) {
									map.set(data.name, data.version);
								}
							} catch {
								/* ignore */
							}
						}
					}
				}
			}
		} catch {
			/* ignore */
		}
	}
	return map;
}

interface PackageDiff {
	updated: { name: string; from: string; to: string; isConfigured: boolean }[];
	added: { name: string; to: string; isConfigured: boolean }[];
	removed: { name: string; from: string; isConfigured: boolean }[];
}

function diffSnapshots(
	before: Map<string, string>,
	after: Map<string, string>,
	configured: Set<string>,
): PackageDiff {
	const updated: { name: string; from: string; to: string; isConfigured: boolean }[] = [];
	const added: { name: string; to: string; isConfigured: boolean }[] = [];
	const removed: { name: string; from: string; isConfigured: boolean }[] = [];

	for (const [name, afterVer] of after.entries()) {
		const beforeVer = before.get(name);
		const isConfigured = configured.has(name);
		if (!beforeVer) {
			added.push({ name, to: afterVer, isConfigured });
		} else if (beforeVer !== afterVer) {
			updated.push({ name, from: beforeVer, to: afterVer, isConfigured });
		}
	}

	for (const [name, beforeVer] of before.entries()) {
		if (!after.has(name)) {
			const isConfigured = configured.has(name);
			removed.push({ name, from: beforeVer, isConfigured });
		}
	}

	const sortFn = (a: { name: string; isConfigured: boolean }, b: { name: string; isConfigured: boolean }) => {
		if (a.isConfigured !== b.isConfigured) return a.isConfigured ? -1 : 1;
		return a.name.localeCompare(b.name);
	};

	updated.sort(sortFn);
	added.sort(sortFn);
	removed.sort(sortFn);

	return { updated, added, removed };
}

interface UpdateSummary {
	/** "0.84.0 → 0.84.1" when pi itself was updated */
	piChanged: string | null;
	/** "v0.84.1" when pi printed "is already up to date" */
	piCurrent: string | null;
	/** e.g. "added 3 packages, changed 2 packages, removed 1 package" */
	packageDelta: string | null;
	/** per-source "Updating X..." lines (e.g. git/npm single sources) */
	updatedSources: string[];
	/** true when anything actually changed */
	changed: boolean;
}

/**
 * Parse `pi update` output into an accurate summary.
 */
function summarize(out: string): UpdateSummary {
	const piChangedMatch = out.match(/Updated\s+(?:π|pi)\s+from\s+v?([\d.]+)\s+to\s+v?([\d.]+)/i);
	const piCurrentMatch = out.match(/(?:π|pi)\s+is\s+already\s+up\s+to\s+date\s+\(v?([\d.]+)\)/i);

	const deltaParts: string[] = [];
	for (const kw of ["added", "changed", "removed"] as const) {
		const m = out.match(new RegExp(`${kw}\\s+(\\d+)\\s+packages?`));
		if (m && parseInt(m[1], 10) > 0) {
			deltaParts.push(`${kw} ${m[1]} package${m[1] === "1" ? "" : "s"}`);
		}
	}

	const lines = out.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
	const updatedSources = lines
		.map((l) => l.match(/^Updating\s+(.+?)\.\.\.$/i)?.[1])
		.filter((s): s is string => Boolean(s))
		.filter((s) => !/^(?:user|project)\s+npm\s+packages?$/i.test(s))
		.filter((s) => !/^(?:π|pi)(?:\s|$)/i.test(s));
	const npmBatchRan = /^Updating\s+(?:user|project)\s+npm\s+packages?\.\.\./im.test(out);
	// npm's own "no change" verdict — the batch ran but npm reported nothing to do
	const npmSaysUpToDate = /\bup\s+to\s+date\b/i.test(out);

	const changed = Boolean(piChangedMatch)
		|| deltaParts.length > 0
		|| updatedSources.length > 0
		|| (npmBatchRan && !npmSaysUpToDate);

	return {
		piChanged: piChangedMatch ? `${piChangedMatch[1]} → ${piChangedMatch[2]}` : null,
		piCurrent: piCurrentMatch ? `v${piCurrentMatch[1]}` : null,
		packageDelta: deltaParts.length ? deltaParts.join(", ") : null,
		updatedSources,
		changed,
	};
}

function formatUpdateMessage(opts: {
	elapsed: number;
	isPiOnly: boolean;
	isExtOnly: boolean;
	packageDiff: PackageDiff;
	packageDelta: string | null;
	updatedSources: string[];
	piChanged: string | null;
	piCurrent: string | null;
	piBefore: string | null;
	piAfter: string | null;
}): string {
	const lines: string[] = [`✅ Update complete (${opts.elapsed}s)`];

	// Packages section (shown unless user specified /update pi)
	if (!opts.isPiOnly) {
		lines.push("", "Packages:");
		const pkgLines: string[] = [];

		for (const u of opts.packageDiff.updated) {
			pkgLines.push(`- ${u.name} (${u.from} → ${u.to})`);
		}
		for (const a of opts.packageDiff.added) {
			pkgLines.push(`- ${a.name} (added v${a.to})`);
		}
		for (const r of opts.packageDiff.removed) {
			pkgLines.push(`- ${r.name} (removed)`);
		}
		for (const src of opts.updatedSources) {
			if (!pkgLines.some((l) => l.includes(src))) {
				pkgLines.push(`- ${src}`);
			}
		}

		if (pkgLines.length > 0) {
			lines.push(...pkgLines);
		} else if (opts.packageDelta && opts.packageDelta !== "0 packages") {
			lines.push(`- ${opts.packageDelta}`);
		} else {
			lines.push("- All packages already up to date");
		}
	}

	// Pi section (shown unless user specified /update ext)
	if (!opts.isExtOnly) {
		lines.push("", "Pi:");
		if (opts.piChanged) {
			lines.push(`- Updated (${opts.piChanged})`);
		} else if (opts.piBefore && opts.piAfter && opts.piBefore !== opts.piAfter) {
			lines.push(`- Updated (${opts.piBefore} → ${opts.piAfter})`);
		} else if (opts.piCurrent) {
			lines.push(`- Already up to date (${opts.piCurrent})`);
		} else if (opts.piAfter) {
			lines.push(`- Already up to date (v${opts.piAfter})`);
		} else {
			lines.push("- Already up to date");
		}
	}

	return lines.join("\n");
}

export default function (pi: ExtensionAPI): void {
	pi.registerCommand("update", {
		description: "Update pi and all extensions. /update [pi|ext]",
		getArgumentCompletions: (prefix: string) => {
			const base = [
				{ value: "pi", label: "pi", description: "Update pi only" },
				{ value: "ext", label: "ext", description: "Update extensions only" },
			];
			if (!prefix) return base;
			return base.filter((c) => c.value.startsWith(prefix));
		},
		handler: async (args, ctx: ExtensionCommandContext) => {
			const arg = args.trim().toLowerCase();
			let flags: string[] = [];
			let label = "pi + all extensions";
			const isPiOnly = arg === "pi" || arg === "self";
			const isExtOnly = arg === "ext" || arg === "extensions";

			if (isPiOnly) {
				flags = ["--self"];
				label = "pi only";
			} else if (isExtOnly) {
				flags = ["--extensions"];
				label = "extensions only";
			} else {
				flags = ["--all"];
			}

			// Confirm
			const confirmed = await ctx.ui.confirm("Run pi update", `Update ${label} now? This may take a minute.`);
			if (!confirmed) {
				ctx.ui.notify("Update canceled.", "info");
				return;
			}

			// Take pre-update snapshot of installed packages & pi version
			const agentDir = getAgentDir();
			const cwd = process.cwd();
			const configuredPackages = getConfiguredPackageNames(agentDir, cwd);
			const packagesBefore = getInstalledPackagesSnapshot(agentDir, cwd);
			const bin = resolvePiBinary();
			const piBefore = getPiVersion(bin);

			// Start — live progress shown as a widget above the input
			const WIDGET_KEY = "pi-update";
			ctx.ui.setWidget(WIDGET_KEY, [`Updating ${label}… 0s`]);
			const startedAt = Date.now();

			// `pi update [--self|--extensions|--all]`
			const piArgs = ["update", ...flags];

			const cmd = IS_WIN && /\.(cmd|bat)$/i.test(bin) ? `"${bin}"` : bin;
			const child = IS_WIN
				? spawn(cmd, piArgs, {
					env: UPDATE_ENV,
					stdio: ["ignore", "pipe", "pipe"],
					shell: true,
					windowsHide: true,
				})
				: spawn(cmd, piArgs, {
					env: UPDATE_ENV,
					stdio: ["ignore", "pipe", "pipe"],
				});

			let allOut = "";
			child.stdout.on("data", (chunk: Buffer) => { allOut += chunk.toString("utf8"); });
			child.stderr.on("data", (chunk: Buffer) => { allOut += chunk.toString("utf8"); });

			const ticker = setInterval(() => {
				const secs = Math.round((Date.now() - startedAt) / 1000);
				const recent = allOut.split(/\r?\n/).map(cleanLine).filter(Boolean).slice(-3);
				ctx.ui.setWidget(WIDGET_KEY, [`Updating ${label}… ${secs}s`, ...recent]);
			}, 1000);

			const code: number = await new Promise((resolve) => {
				child.on("close", (c) => resolve(c ?? 1));
				child.on("error", () => resolve(1));
			});

			clearInterval(ticker);
			ctx.ui.setWidget(WIDGET_KEY, undefined);

			const elapsed = Math.round((Date.now() - startedAt) / 1000);
			const out = allOut.trim();
			const s = summarize(out);

			if (code !== 0) {
				const errTail = out.split(/\r?\n/).filter(Boolean).slice(-2).map(cleanLine).join(" | ");
				const headline = s.changed
					? `⚠️ ${label}: updates applied, but pi reported an error — ${errTail || "see console"}`
					: `❌ Update failed (${elapsed}s): ${errTail || "see console"}`;
				ctx.ui.notify(headline, "error");
				return;
			}

			// Take post-update snapshot of installed packages & pi version
			const packagesAfter = getInstalledPackagesSnapshot(agentDir, cwd);
			const piAfter = getPiVersion(bin);
			const packageDiff = diffSnapshots(packagesBefore, packagesAfter, configuredPackages);

			const message = formatUpdateMessage({
				elapsed,
				isPiOnly,
				isExtOnly,
				packageDiff,
				packageDelta: s.packageDelta,
				updatedSources: s.updatedSources,
				piChanged: s.piChanged,
				piCurrent: s.piCurrent,
				piBefore,
				piAfter,
			});

			ctx.ui.notify(message, "info");
		},
	});
}
