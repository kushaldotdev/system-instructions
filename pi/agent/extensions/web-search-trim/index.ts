/**
 * web-search-trim — slash command to trim pi-web-access's provider list
 * in the tool schemas, without touching startup, hooks, or session_start.
 *
 * What it does:
 *   /web-search-trim [openai exa tavily ...]   interactive or explicit keep-list
 *   /web-search-trim reset                     restore full provider list
 *   /web-search-trim status                    show current state
 *
 * It patches the pi-web-access package source files in place:
 *   - gemini-search.ts : RESOLVED_SEARCH_PROVIDERS (schema enum) + ALL_SEARCH_PROVIDERS (runtime chain)
 *   - index.ts         : the long web_search description (provider prose)
 * source_check's provider enum is trimmed too (both tools share searchProviderSchema),
 * but its short description needs no patch.
 * A backup of each patched file is kept next to it (.web-search-trim.bak) so
 * /web-search-trim reset can restore the original.
 *
 * Update story: `pi update --all` reinstalls pi-web-access, wiping the patch.
 * Re-run /web-search-trim after an update (that's expected — no startup hook).
 */

import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const PACKAGE_NAME = "pi-web-access";

// All resolvable providers as defined by the package.
const ALL_PROVIDERS = [
	"openai", "brave", "parallel", "tinyfish", "search1api", "searchinfinity",
	"querit", "tavily", "jina", "searxng", "perplexity", "gemini", "exa",
	"serpdive", "kagi", "ollama", "anysearch", "xai", "brightdata", "serpbase",
] as const;

// Display labels (used in the interactive picker).
const PROVIDER_LABELS: Record<string, string> = {
	openai: "OpenAI (Codex)",
	brave: "Brave",
	parallel: "Parallel",
	tinyfish: "TinyFish",
	search1api: "Search1API",
	searchinfinity: "Searchinfinity",
	querit: "Querit",
	tavily: "Tavily",
	jina: "Jina",
	searxng: "SearXNG (self-hosted)",
	perplexity: "Perplexity",
	gemini: "Gemini",
	exa: "Exa",
	serpdive: "SERPdive",
	kagi: "Kagi",
	ollama: "Ollama",
	anysearch: "AnySearch",
	xai: "xAI/Grok",
	brightdata: "Bright Data",
	serpbase: "SerpBase",
};

// Where the package files live. Resolve via the same dir logic pi uses
// (~/.pi/agent/npm/node_modules/<name>).
function packageDir(): string {
	const agentDir = process.env.PI_CODING_AGENT_DIR
		|| (process.env.XDG_CONFIG_HOME ? path.join(process.env.XDG_CONFIG_HOME, "pi") : path.join(os.homedir(), ".pi"));
	return path.join(agentDir, "agent", "npm", "node_modules", PACKAGE_NAME);
}

function geminiSearchPath(): string { return path.join(packageDir(), "gemini-search.ts"); }
function indexPath(): string { return path.join(packageDir(), "index.ts"); }

// ---------------------------------------------------------------------------
// Config file: ~/.pi/agent/extensions/web-search-trim/config.json
// ---------------------------------------------------------------------------
function configPath(): string {
	return path.join(os.homedir(), ".pi", "agent", "extensions", "web-search-trim", "config.json");
}

interface TrimConfig {
	keep?: string[];
	enabled?: boolean;
}

function readConfig(): TrimConfig {
	try {
		const raw = fs.readFileSync(configPath(), "utf8");
		const parsed = JSON.parse(raw);
		if (parsed && typeof parsed === "object") return parsed as TrimConfig;
	} catch { /* missing or invalid */ }
	return {};
}

function writeConfig(cfg: TrimConfig): void {
	fs.mkdirSync(path.dirname(configPath()), { recursive: true });
	fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2) + "\n", "utf8");
}

// ---------------------------------------------------------------------------
// API-key detection (mirrors the package's own credential checks)
// ---------------------------------------------------------------------------
function loadWebSearchConfig(): Record<string, unknown> {
	try {
		const dir = process.env.PI_CODING_AGENT_DIR
			|| (process.env.XDG_CONFIG_HOME ? path.join(process.env.XDG_CONFIG_HOME, "pi") : path.join(os.homedir(), ".pi"));
		const p = path.join(dir, "web-search.json");
		return JSON.parse(fs.readFileSync(p, "utf8"));
	} catch {
		return {};
	}
}

function hasKey(...candidates: Array<string | undefined>): boolean {
	return candidates.some((c) => typeof c === "string" && c.trim().length > 0);
}

// Which providers look configured. Mirrors the package's OWN availability logic:
//  - Exa is ALWAYS available (zero-config via MCP, no key needed)
//  - OpenAI is available via Codex login (pi auth.json / model registry) OR an API key
//  - Others need an API key in web-search.json or env
function configuredProviders(ctx?: { modelRegistry?: { getAll(): Array<{ provider: string }> } }): Set<string> {
	const cfg = loadWebSearchConfig();
	const env = process.env;
	const set = new Set<string>();

	// OpenAI: key OR Codex login (pi auth / model registry)
	const hasOpenAiKey = hasKey(cfg.openaiApiKey as string, env.OPENAI_API_KEY);
	const hasCodexAuth = (() => {
		// pi auth.json holds oauth tokens (e.g. openai-codex)
		try {
			const authPath = path.join(os.homedir(), ".pi", "agent", "auth.json");
			const auth = JSON.parse(fs.readFileSync(authPath, "utf8"));
			if (auth && typeof auth === "object") {
				const providers = Object.keys(auth);
				if (providers.some((p) => p.toLowerCase().includes("openai") || p.toLowerCase().includes("codex"))) return true;
			}
		} catch { /* no auth file */ }
		// model registry (ctx) — openai / openai-codex providers present
		if (ctx?.modelRegistry?.getAll) {
			try {
				const models = ctx.modelRegistry.getAll();
				if (models.some((m) => m.provider === "openai" || m.provider === "openai-codex")) return true;
			} catch { /* registry unavailable */ }
		}
		return false;
	})();
	if (hasOpenAiKey || hasCodexAuth) set.add("openai");

	// Exa: always available (zero-config MCP) — no key required
	set.add("exa");

	// The rest need explicit keys
	if (hasKey(cfg.tavilyApiKey as string, env.TAVILY_API_KEY)) set.add("tavily");
	if (hasKey(cfg.braveApiKey as string, env.BRAVE_API_KEY)) set.add("brave");
	if (hasKey(cfg.parallelApiKey as string, env.PARALLEL_API_KEY)) set.add("parallel");
	if (hasKey(cfg.tinyfishApiKey as string, env.TINYFISH_API_KEY)) set.add("tinyfish");
	if (hasKey(cfg.search1apiApiKey as string, env.SEARCH1API_API_KEY)) set.add("search1api");
	if (hasKey(cfg.searchinfinityApiKey as string, env.SEARCHINFINITY_API_KEY)) set.add("searchinfinity");
	if (hasKey(cfg.queritApiKey as string, env.QUERIT_API_KEY)) set.add("querit");
	if (hasKey(cfg.jinaApiKey as string, env.JINA_API_KEY)) set.add("jina");
	if (hasKey(cfg.kagiApiKey as string, env.KAGI_API_KEY)) set.add("kagi");
	if (hasKey(cfg.ollamaApiKey as string, env.OLLAMA_API_KEY)) set.add("ollama");
	if (hasKey(cfg.perplexityApiKey as string, env.PERPLEXITY_API_KEY)) set.add("perplexity");
	if (hasKey(cfg.geminiApiKey as string, env.GEMINI_API_KEY)) set.add("gemini");
	if (hasKey(cfg.serpdiveApiKey as string, env.SERPDIVE_API_KEY)) set.add("serpdive");
	if (hasKey(cfg.serpbaseApiKey as string, env.SERPBASE_API_KEY)) set.add("serpbase");
	if (hasKey(cfg.anysearchApiKey as string, env.ANYSEARCH_API_KEY)) set.add("anysearch");
	if (hasKey(cfg.xaiApiKey as string, env.XAI_API_KEY)) set.add("xai");
	if (hasKey(cfg.brightdataApiKey as string, env.BRIGHTDATA_API_KEY)) set.add("brightdata");
	if (hasKey(cfg.searxngBaseUrl as string, env.SEARXNG_URL)) set.add("searxng");
	return set;
}

// ---------------------------------------------------------------------------
// Source patching
// ---------------------------------------------------------------------------
function backupFile(filePath: string): void {
	const bak = filePath + ".web-search-trim.bak";
	if (!fs.existsSync(bak)) fs.copyFileSync(filePath, bak);
}

function restoreBackup(filePath: string): boolean {
	const bak = filePath + ".web-search-trim.bak";
	if (!fs.existsSync(bak)) return false;
	fs.copyFileSync(bak, filePath);
	return true;
}

// Patch gemini-search.ts: replace the RESOLVED_SEARCH_PROVIDERS (schema enum)
// AND ALL_SEARCH_PROVIDERS (runtime fallback chain for `all` mode) with the keep-list.
// Trimming the enum without the chain would throw on removed providers in array form;
// trimming both keeps schema + runtime consistent.
function patchGeminiSearch(keep: string[]): void {
	const file = geminiSearchPath();
	backupFile(file);
	let src = fs.readFileSync(file, "utf8");

	const re = /export const RESOLVED_SEARCH_PROVIDERS = \[[\s\S]*?\] as const;/;
	if (!re.test(src)) throw new Error("Could not find RESOLVED_SEARCH_PROVIDERS in gemini-search.ts");
	src = src.replace(re, `export const RESOLVED_SEARCH_PROVIDERS = ${JSON.stringify(keep)} as const;`);

	const re2 = /const ALL_SEARCH_PROVIDERS: ResolvedSearchProvider\[\] = \[[\s\S]*?\];/;
	if (!re2.test(src)) throw new Error("Could not find ALL_SEARCH_PROVIDERS in gemini-search.ts");
	src = src.replace(re2, `const ALL_SEARCH_PROVIDERS: ResolvedSearchProvider[] = ${JSON.stringify(keep)};`);

	fs.writeFileSync(file, src, "utf8");
}

// Patch index.ts: replace the long web_search description (names every provider)
// with a trimmed one. source_check's description is short/generic — no patch needed.
// Its provider enum is trimmed via gemini-search.ts (both tools call searchProviderSchema).
function patchIndexDescriptions(keep: string[]): void {
	const file = indexPath();
	backupFile(file);
	let src = fs.readFileSync(file, "utf8");

	const keepHuman = keep.map((k) => PROVIDER_LABELS[k] ?? k).join(", ");
	const keepIds = keep.join(", ");

	// web_search description
	const webRe = /description:\s*`Search the web using[\s\S]*?local\/private search\.`,/;
	const webDesc = `Search the web using ${keepHuman}. Pass a provider array to search only those providers simultaneously, or use provider "all" to search every eligible provider. Returns an AI-synthesized answer with source citations. When includeContent is true, full page content is fetched in the background. Searches auto-open the interactive browser curator and stream results live; set workflow to "none" to skip curation or "auto-summary" for a model-generated summary without the browser curator. The configured provider is used when provider is omitted or set to auto; omit provider unless explicitly overriding it. Available providers: ${keepIds}.`;
	if (!webRe.test(src)) throw new Error("Could not find web_search description in index.ts");
	src = src.replace(webRe, `description: \`${webDesc}\`,`);

	fs.writeFileSync(file, src, "utf8");
}

function patch(keep: string[]): void {
	patchGeminiSearch(keep);
	patchIndexDescriptions(keep);
	writeConfig({ enabled: true, keep });
}

function restoreAll(): void {
	const g = geminiSearchPath();
	const i = indexPath();
	const okG = restoreBackup(g);
	const okI = restoreBackup(i);
	if (!okG && !okI) throw new Error("No backup found — nothing to restore. (Package may have been updated since the trim.)");
	fs.rmSync(configPath(), { force: true });
}

function isTrimmed(): boolean {
	try {
		const src = fs.readFileSync(geminiSearchPath(), "utf8");
		const m = src.match(/export const RESOLVED_SEARCH_PROVIDERS = \[([\s\S]*?)\] as const;/);
		if (!m) return false;
		const ids = [...m[1].matchAll(/"([a-z0-9]+)"/g)].map((x) => x[1]);
		// Trimmed = the current list differs from the full original list.
		return ids.length !== ALL_PROVIDERS.length
			|| ALL_PROVIDERS.some((p, i) => ids[i] !== p);
	} catch {
		return false;
	}
}

// ---------------------------------------------------------------------------
// Slash command
// ---------------------------------------------------------------------------
export default function (pi: ExtensionAPI): void {
	pi.registerCommand("web-search-trim", {
		description:
			"Trim pi-web-access provider list in tool schemas. /web-search-trim [providers...] | reset | status",
		getArgumentCompletions: (prefix: string) => {
			const base = [
				{ value: "reset", label: "reset", description: "Restore full provider list" },
				{ value: "status", label: "status", description: "Show current trim state + configured providers" },
				...ALL_PROVIDERS.map((p) => ({
					value: p,
					label: p,
					description: PROVIDER_LABELS[p],
				})),
			];
			if (!prefix) return base;
			return base.filter((c) => c.value.startsWith(prefix));
		},
		handler: async (args, ctx: ExtensionCommandContext) => {
			const arg = args.trim();
			const ui = ctx.ui;

			// status
			if (arg === "status" || arg === "--status") {
				const cfg = readConfig();
				const configured = configuredProviders(ctx);
				const trimmed = isTrimmed();
				const lines = [
					`Trim enabled: ${cfg.enabled ? "yes" : "no"} (source ${trimmed ? "patched" : "unpatched"})`,
					`Keep-list: ${cfg.keep?.length ? cfg.keep.join(", ") : "none (all providers)"}`,
					`Available: ${[...configured].map((p) => PROVIDER_LABELS[p]).join(", ") || "none"}`,
				];
				ui.notify(lines.join("\n"), "info");
				return;
			}

			// reset
			if (arg === "reset" || arg === "--reset") {
				try {
					restoreAll();
					ui.notify("Restored full provider list. Run /reload for it to take effect.", "info");
				} catch (e) {
					ui.notify(`Reset failed: ${(e as Error).message}`, "error");
				}
				return;
			}

			// explicit keep-list
			if (arg) {
				const requested = arg.split(/\s+/).filter(Boolean);
				const invalid = requested.filter((p) => !ALL_PROVIDERS.includes(p as (typeof ALL_PROVIDERS)[number]));
				if (invalid.length) {
					ui.notify(`Unknown provider(s): ${invalid.join(", ")}. Valid: ${ALL_PROVIDERS.join(", ")}`, "warning");
					return;
				}
				try {
					patch(requested);
					ui.notify(`Trimmed to: ${requested.join(", ")}. Run /reload for it to take effect.`, "info");
				} catch (e) {
					ui.notify(`Patch failed: ${(e as Error).message}`, "error");
				}
				return;
			}

			// interactive picker (toggle loop)
			const configured = configuredProviders(ctx);
			const cfg = readConfig();
			let current = new Set<string>(cfg.keep ?? []);
			if (current.size === 0) current = new Set(ALL_PROVIDERS); // default: all on

			for (;;) {
				const options: string[] = [];
				const toggles: string[] = [];
				for (const p of ALL_PROVIDERS) {
					const on = current.has(p);
					const mark = on ? "✓" : " ";
					const cfgMark = configured.has(p) ? " ✅available" : "";
					options.push(`[${mark}] ${PROVIDER_LABELS[p]}${cfgMark}`);
					toggles.push(p);
				}
				const header = `Providers to keep (current: ${current.size}/${ALL_PROVIDERS.length}) — pick to toggle:`;
				const doneLabel = "--- Done / apply trim ---";
				const availLabel = "Keep only the available ones (Codex login / zero-config / API key)";
				const resetLabel = "Restore all defaults (reset)";
				options.push(doneLabel, availLabel, resetLabel);

				const choice = await ui.select(header, options);
				if (!choice) {
					ui.notify("Canceled.", "info");
					return;
				}
				// Toggle a provider row (rows start with "[") — match by exact option text.
				const toggleIdx = options.indexOf(choice);
				if (choice.startsWith("[") && toggleIdx >= 0 && toggleIdx < toggles.length) {
					const p = toggles[toggleIdx];
					if (current.has(p)) current.delete(p); else current.add(p);
					continue;
				}
				if (choice === doneLabel) {
					const keep = [...current];
					if (keep.length === 0) {
						ui.notify("You must keep at least one provider.", "warning");
						continue;
					}
					try {
						patch(keep);
						ui.notify(`Trimmed to: ${keep.join(", ")}. Run /reload for it to take effect.`, "info");
					} catch (e) {
						ui.notify(`Patch failed: ${(e as Error).message}`, "error");
					}
					return;
				}
				if (choice === availLabel) {
					current = new Set(configured);
					continue;
				}
				if (choice === resetLabel) {
					try {
						restoreAll();
						ui.notify("Restored full provider list. Run /reload for it to take effect.", "info");
					} catch (e) {
						ui.notify(`Reset failed: ${(e as Error).message}`, "error");
					}
					return;
				}
			}
		},
	});
}
