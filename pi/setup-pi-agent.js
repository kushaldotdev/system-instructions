#!/usr/bin/env node
// ============================================================================
// setup-pi-agent.js — Pi Agent idempotent provisioner (Windows / Linux / WSL)
// ----------------------------------------------------------------------------
// Run:  node setup-pi-agent.js                      (provisions the WSL/Linux side)
//       node setup-pi-agent.js --target windows     (provisions the Windows side)
//       node setup-pi-agent.js --env NINE_ROUTER=sk-xxx --env NINE_ROUTER_BASE_URL=https://my-proxy.com/v1
//
// Target selection (default: wsl when running inside WSL, windows on a Windows
// host, native elsewhere):
//       --target wsl      provision the WSL/Linux user environment
//       --target windows  provision the Windows user environment (from inside
//                          WSL this uses cmd.exe interop + /mnt/c filesystem)
//
// What it does (safe to re-run any number of times):
//   1. Creates ~/.pi/{,.env,agent,agent/extensions} structure.
//   2. Manages ~/.pi/.env with SMART merge:
//        - key missing            -> written (placeholder or provided value)
//        - key present but BLANK  -> overwritten (placeholder or provided value)
//        - key present = demo/default placeholder -> replaced when a real value is provided
//        - key present = real value -> PRESERVED (never clobbered)
//      Provided values come from `--env KEY=value` args or the shell environment.
//   3. Configures ~/.pi/web-search.json and ~/.pi/agent/auth.json (preserves tokens).
//   4. Merges ~/.pi/agent/settings.json packages WITHOUT duplicating entries, and
//      replaces the old always-on `9router-discovery.ts` hook with the
//      `9router-sync.ts` extension (automatic schema sanitizer + on-demand
//      model sync; migration is automatic).
//   5. Installs the `rtk` Rust binary automatically if missing (official installer
//      on POSIX, GitHub release download on Windows) and ensures ~/.local/bin is
//      on PATH for future shells.
//   6. Ensures `agent-browser` CLI + Chrome for Testing + ffmpeg are present so the
//      `agent_browser` tool works out of the box.
//   7. Installs/verifies the pi packages listed in `requiredPackages`.
//
// IMPORTANT: npm-installed extension packages (pi-agent-browser-native,
// pi-rtk-optimizer, ...) are NEVER modified. All customization lives in separate
// top-level files under ~/.pi/agent/extensions/, so future package updates cannot
// overwrite our code.
// ============================================================================

const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");
const child_process = require("child_process");

const HOST_IS_WINDOWS = process.platform === "win32";
const HOST_IS_WSL = !HOST_IS_WINDOWS && !!process.env.WSL_DISTRO_NAME;

// ---------------------------------------------------------------------------
// 0. Target selection: --target wsl | windows
//    Default: windows on a Windows host, wsl inside WSL, native elsewhere.
// ---------------------------------------------------------------------------
function parseTargetArg() {
	const argv = process.argv;
	const i = argv.indexOf("--target");
	if (i !== -1 && argv[i + 1]) return argv[i + 1].toLowerCase();
	const eq = argv.find((a) => a.startsWith("--target="));
	if (eq) return eq.split("=")[1].toLowerCase();
	return undefined;
}

const TARGET =
	parseTargetArg() ??
	(HOST_IS_WINDOWS ? "windows" : HOST_IS_WSL ? "wsl" : "native");
const TARGET_IS_WINDOWS = TARGET === "windows";
if (!["wsl", "windows", "native"].includes(TARGET)) {
	console.error(`[!] Unknown --target '${TARGET}'. Supported: wsl | windows`);
	process.exit(1);
}
if (TARGET === "wsl" && HOST_IS_WINDOWS) {
	console.error(
		"[!] --target wsl requires running inside WSL (no WSL interop on a native Windows host).",
	);
	process.exit(1);
}
if (TARGET === "windows" && !HOST_IS_WINDOWS && !HOST_IS_WSL) {
	console.error(
		"[!] --target windows requires a Windows host or WSL with /mnt access.",
	);
	process.exit(1);
}

// Windows user profile as a WSL-style path when provisioning Windows from WSL
// (e.g. C:\Users\Kushal -> /mnt/c/Users/Kushal via %USERPROFILE% + wslpath).
function resolveWindowsHomeFromWsl() {
	try {
		// bare `cmd.exe` does NOT resolve from WSL bash (Windows exes aren't on the
		// WSL PATH) — use the full /mnt/c path; WSL interop runs it directly.
		const out = child_process.execSync(
			'/mnt/c/Windows/System32/cmd.exe /d /c "echo %USERPROFILE%"',
			{
				encoding: "utf8",
				stdio: ["ignore", "pipe", "ignore"],
			},
		);
		const win = String(out)
			.split(/\r?\n/)
			.map((l) => l.trim())
			.find((l) => /^[A-Za-z]:\\/.test(l));
		if (win) {
			const wsl = child_process
				.execSync(`wslpath -u '${win}'`, { encoding: "utf8" })
				.trim();
			if (wsl && fs.existsSync(wsl)) return wsl;
		}
	} catch {
		// fall through
	}
	try {
		if (process.env.USER && fs.existsSync(`/mnt/c/Users/${process.env.USER}`)) {
			return `/mnt/c/Users/${process.env.USER}`;
		}
	} catch {
		// fall through
	}
	return null;
}

// WSL-style path of the TARGET user home (what config files should be written to).
let TARGET_HOME = os.homedir();
if (TARGET_IS_WINDOWS && !HOST_IS_WINDOWS) {
	TARGET_HOME = resolveWindowsHomeFromWsl();
	if (!TARGET_HOME) {
		console.error(
			"[!] Could not resolve the Windows user profile from WSL (cmd.exe interop + wslpath).",
		);
		process.exit(1);
	}
}

// Convert a WSL-style path to a Windows-style path (identity on a native Windows host).
function toWinPath(wslPath) {
	if (HOST_IS_WINDOWS) return wslPath;
	try {
		return child_process
			.execSync(`wslpath -w '${wslPath}'`, { encoding: "utf8" })
			.trim();
	} catch {
		return wslPath;
	}
}

// Windows system-tool invocations. On a native Windows host the bare command
// name resolves via PATH; from WSL, Windows exes are NOT on the WSL PATH, so use
// the full /mnt/c path (interop runs it directly).
const WIN_CMD = HOST_IS_WINDOWS ? "cmd.exe" : "/mnt/c/Windows/System32/cmd.exe";
const WIN_WHERE = HOST_IS_WINDOWS
	? "where.exe"
	: "/mnt/c/Windows/System32/where.exe";
const WIN_PS = HOST_IS_WINDOWS
	? "powershell.exe"
	: "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe";
// cwd that maps to a real Windows dir so cmd.exe doesn't complain about UNC paths
const WIN_CWD = TARGET_IS_WINDOWS && !HOST_IS_WINDOWS ? TARGET_HOME : undefined;

console.log("=============================================");
console.log("   Pi Agent Idempotent Node Provisioner      ");
console.log("   (Windows / Linux / WSL)                   ");
console.log(
	`   Target: ${TARGET}${TARGET_IS_WINDOWS && !HOST_IS_WINDOWS ? ` (${TARGET_HOME})` : ""}   `,
);
console.log("=============================================");

// ---------------------------------------------------------------------------
// 0. CLI argument parsing: --env KEY=VALUE (repeatable) or bare KEY=VALUE
//    --no-install : only write config files, skip binary/package installs
// ---------------------------------------------------------------------------
function parseEnvArgs(argv) {
	const provided = {};
	for (const arg of argv.slice(2)) {
		const m = arg.match(
			/^(?:--env\s*=\s*|--env\s+|)([A-Za-z_][A-Za-z0-9_]*)=(.*)$/,
		);
		if (m) {
			provided[m[1]] = m[2];
		}
	}
	return provided;
}

const cliEnv = parseEnvArgs(process.argv);
const NO_INSTALL = process.argv.includes("--no-install");
if (NO_INSTALL)
	console.log(
		"[i] --no-install: skipping binary/package installs, config files only",
	);

// ---------------------------------------------------------------------------
// 1. Directory Paths (resolved against the TARGET home)
// ---------------------------------------------------------------------------
const PI_DIR = path.join(TARGET_HOME, ".pi");
const AGENT_DIR = path.join(PI_DIR, "agent");
const EXT_DIR = path.join(AGENT_DIR, "extensions");
const LOCAL_BIN = path.join(TARGET_HOME, ".local", "bin");

fs.mkdirSync(PI_DIR, { recursive: true });
fs.mkdirSync(AGENT_DIR, { recursive: true });
fs.mkdirSync(EXT_DIR, { recursive: true });

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
function run(cmd, opts = {}) {
	// shell:true lets Windows resolve .cmd/.ps1 shims (npm, pi, where, ...)
	return child_process.execSync(cmd, {
		stdio: "inherit",
		shell: true,
		...opts,
	});
}

function tryRun(cmd, opts = {}) {
	try {
		run(cmd, opts);
		return true;
	} catch {
		return false;
	}
}

// Rewrite a command so it executes against the TARGET environment:
// provisioning Windows from inside WSL wraps commands in cmd.exe (full path)
// so Windows PATH resolution (npm.cmd, pi.cmd, agent-browser.cmd, ...) applies.
// Native Windows and non-Windows targets pass through unchanged.
function forTarget(cmd) {
	if (!(TARGET_IS_WINDOWS && !HOST_IS_WINDOWS)) return cmd;
	return `${WIN_CMD} /d /c "${cmd.replace(/"/g, '\\"')}"`;
}

// Run a command against the TARGET, with the Windows-visible cwd when needed.
function targetRun(cmd, opts = {}) {
	return run(forTarget(cmd), { ...(WIN_CWD ? { cwd: WIN_CWD } : {}), ...opts });
}

function targetTryRun(cmd, opts = {}) {
	try {
		targetRun(cmd, opts);
		return true;
	} catch {
		return false;
	}
}

// Run PowerShell against the Windows target. Writes the script to a temp .ps1 in
// the target .pi dir so path/quoting issues are avoided on both native Windows
// and WSL->Windows interop. PowerShell is invoked directly (full path) — it must
// NOT go through cmd.exe /c (that would mangle the -File argument quoting).
function runWindowsPowerShell(scriptBody) {
	if (!TARGET_IS_WINDOWS) return false;
	const psFile = path.join(PI_DIR, "setup-tmp.ps1");
	try {
		fs.mkdirSync(path.dirname(psFile), { recursive: true });
		fs.writeFileSync(psFile, scriptBody, "utf-8");
		const winPs = toWinPath(psFile);
		const cmd = `${WIN_PS} -NoProfile -ExecutionPolicy Bypass -File "${winPs}"`;
		const ok = tryRun(cmd, WIN_CWD ? { cwd: WIN_CWD } : {});
		return ok;
	} finally {
		try {
			fs.rmSync(psFile, { force: true });
		} catch {
			// ignore
		}
	}
}

function commandOnPath(name) {
	try {
		let probe;
		if (TARGET_IS_WINDOWS && !HOST_IS_WINDOWS) {
			// from WSL, query the Windows PATH via where.exe (full path) interop
			probe = `${WIN_WHERE} ${name}`;
		} else if (HOST_IS_WINDOWS || TARGET_IS_WINDOWS) {
			probe = `where ${name}`;
		} else {
			probe = `which ${name}`;
		}
		const out = child_process.execSync(probe, {
			stdio: ["ignore", "pipe", "ignore"],
			...(WIN_CWD ? { cwd: WIN_CWD } : {}),
		});
		const first = String(out)
			.split(/\r?\n/)
			.map((s) => s.trim())
			.filter(Boolean)[0];
		return first || null;
	} catch {
		return null;
	}
}

function pathContains(dir) {
	const parts = (process.env.PATH || "").split(path.delimiter).filter(Boolean);
	return parts.some(
		(p) => path.resolve(p.replace(/^"(.*)"$/, "$1")) === path.resolve(dir),
	);
}

function quoteValue(v) {
	return `"${String(v).replace(/"/g, '\\"')}"`;
}

// ---------------------------------------------------------------------------
// 2. Smart ~/.pi/.env merge
//    blank -> overwrite | demo/default placeholder -> replace with provided | real -> preserve
// ---------------------------------------------------------------------------
const ENV_FILE = path.join(PI_DIR, ".env");

// placeholder values the script considers "empty / default / demo" and may replace.
// NOTE: model/provider API keys (ANTHROPIC, OPENAI, GEMINI, ...) are intentionally
// NOT managed here — this is only for tool/extension keys (web search, 9Router,
// agent-browser providers). Configure model keys via `pi /login` or auth.json.
const ENV_PLACEHOLDERS = {
	// --- Web search providers (pi-web-access) ---
	TAVILY_API_KEY: '""',
	BRAVE_API_KEY: '""',
	EXA_API_KEY: '""',
	PARALLEL_API_KEY: '""',
	TINYFISH_API_KEY: '""',
	SEARCH1API_KEY: '""',
	SEARCHINFINITY_API_KEY: '""',
	QUERIT_API_KEY: '""',
	SERPDIVE_API_KEY: '""',
	KAGI_API_KEY: '""',
	OLLAMA_API_KEY: '""',
	SERPBASE_API_KEY: '""',
	ANYSEARCH_API_KEY: '""',
	BRIGHTDATA_API_KEY: '""',
	BRIGHTDATA_SERP_ZONE: '""',
	BRIGHTDATA_UNLOCKER_ZONE: '""',
	FIRECRAWL_API_KEY: '""',
	PERPLEXITY_API_KEY: '""',
	// --- 9Router proxy ---
	NINE_ROUTER: '""',
	NINE_ROUTER_BASE_URL: '"https://your-9router-proxy-domain.com/v1"',
	// --- agent-browser cloud providers ---
	BROWSERLESS_API_KEY: '""',
	BROWSERBASE_API_KEY: '""',
	BROWSER_USE_API_KEY: '""',
	KERNEL_API_KEY: '""',
};

// Keys auto-generated locally when missing/blank (not listed as blank placeholders).
const AUTO_GENERATED_KEYS = {
	// 64-char hex key for AES-256-GCM state encryption (agent-browser doctor recommends this)
	AGENT_BROWSER_ENCRYPTION_KEY: () => crypto.randomBytes(32).toString("hex"),
};

function readEnvLines() {
	if (!fs.existsSync(ENV_FILE)) return [];
	return fs.readFileSync(ENV_FILE, "utf-8").split(/\r?\n/);
}

function isBlankValue(raw) {
	const v = String(raw).trim();
	return v === "" || v === '""' || v === "''" || v === "`" + "`";
}

function isDefaultPlaceholder(key, raw) {
	const placeholder = ENV_PLACEHOLDERS[key];
	if (!placeholder) return false;
	// quote-insensitive: "demo-url" and demo-url both count as the placeholder
	const bare = (s) =>
		String(s)
			.trim()
			.replace(/^(["'])([\s\S]*)\1$/, "$2");
	return bare(raw) === bare(placeholder);
}

// Normalize any real value to the quoted form ("value"), preserving content.
// Naked real values typed by hand (TAVILY_API_KEY=tvly-...) get quotes added so
// the file is uniformly quoted; quoted values stay byte-identical.
function normalizeQuoted(raw) {
	const v = String(raw).trim();
	const bare = v.replace(/^(["'])([\s\S]*)\1$/, "$2");
	return quoteValue(bare);
}

function mergeEnv() {
	const lines = readEnvLines();
	const keys = Object.keys(ENV_PLACEHOLDERS);
	const autoKeys = Object.keys(AUTO_GENERATED_KEYS);
	let changed = false;

	// current values by key (raw, may include quotes)
	const current = new Map();
	for (const line of lines) {
		const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
		if (m) current.set(m[1], m[2].trim());
	}

	const finalLines = [];
	const seen = new Set();

	for (const line of lines) {
		const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
		if (!m) {
			finalLines.push(line); // comments / blank lines preserved
			continue;
		}
		const key = m[1];
		if (!keys.includes(key)) {
			finalLines.push(line); // unknown keys preserved untouched
			continue;
		}
		const existing = m[2].trim();
		const placeholder = ENV_PLACEHOLDERS[key];
		const provided = cliEnv[key] ?? process.env[key];

		let newRaw;
		if (isBlankValue(existing)) {
			// BLANK -> fill with provided value or placeholder
			newRaw = provided ? quoteValue(provided) : placeholder;
		} else if (isDefaultPlaceholder(key, existing)) {
			// DEFAULT/demo placeholder -> replace when a real value is provided
			newRaw = provided ? quoteValue(provided) : existing;
		} else {
			// REAL value -> preserve content, normalize to quoted form
			newRaw = normalizeQuoted(existing);
		}

		finalLines.push(`${key}=${newRaw}`);
		seen.add(key);
		if (newRaw !== existing) changed = true;
	}

	// add keys that are entirely missing
	for (const key of keys) {
		if (seen.has(key)) continue;
		const provided = cliEnv[key] ?? process.env[key];
		finalLines.push(
			`${key}=${provided ? quoteValue(provided) : ENV_PLACEHOLDERS[key]}`,
		);
		changed = true;
	}

	// auto-generated keys: only written when missing or blank; never clobber an existing value
	for (const key of autoKeys) {
		const existing = current.get(key);
		if (existing && !isBlankValue(existing)) continue; // real value -> keep as-is
		finalLines.push(`${key}=${quoteValue(AUTO_GENERATED_KEYS[key]())}`);
		changed = true;
	}

	if (changed || !fs.existsSync(ENV_FILE)) {
		fs.writeFileSync(
			ENV_FILE,
			finalLines.join("\n").replace(/\n+$/, "") + "\n",
			"utf-8",
		);
		console.log(
			`[+] Updated ${ENV_FILE} (blank/default keys filled, real values preserved)`,
		);
	} else {
		console.log(`[=] ${ENV_FILE} is up to date`);
	}
}

mergeEnv();

// ---------------------------------------------------------------------------
// 3. Cross-platform Web Search Configuration (~/.pi/web-search.json)
// ---------------------------------------------------------------------------
const WEB_SEARCH_FILE = path.join(PI_DIR, "web-search.json");
const ENV_READER = (key) =>
	`!node -e "const fs=require('fs'),p=require('path'),os=require('os');try{const c=fs.readFileSync(p.join(os.homedir(),'.pi','.env'),'utf8'),m=c.match(/^${key}=(.+)$/m);if(m)console.log(m[1].trim().replace(/^[\\'\\"]|[\\'\\"]$/g,''));}catch{}"`;

const defaultWebSearchConfig = {
	provider: "auto",
	// Each key is a `!node` credential source reading the matching var from ~/.pi/.env,
	// so filling .env once activates the provider everywhere.
	tavilyApiKey: ENV_READER("TAVILY_API_KEY"),
	braveApiKey: ENV_READER("BRAVE_API_KEY"),
	exaApiKey: ENV_READER("EXA_API_KEY"),
	parallelApiKey: ENV_READER("PARALLEL_API_KEY"),
	tinyfishApiKey: ENV_READER("TINYFISH_API_KEY"),
	search1apiApiKey: ENV_READER("SEARCH1API_KEY"),
	searchinfinityApiKey: ENV_READER("SEARCHINFINITY_API_KEY"),
	queritApiKey: ENV_READER("QUERIT_API_KEY"),
	serpdiveApiKey: ENV_READER("SERPDIVE_API_KEY"),
	kagiApiKey: ENV_READER("KAGI_API_KEY"),
	ollamaApiKey: ENV_READER("OLLAMA_API_KEY"),
	serpbaseApiKey: ENV_READER("SERPBASE_API_KEY"),
	anysearchApiKey: ENV_READER("ANYSEARCH_API_KEY"),
	brightdataApiKey: ENV_READER("BRIGHTDATA_API_KEY"),
	brightdataSerpZone: ENV_READER("BRIGHTDATA_SERP_ZONE"),
	brightdataUnlockerZone: ENV_READER("BRIGHTDATA_UNLOCKER_ZONE"),
	firecrawlApiKey: ENV_READER("FIRECRAWL_API_KEY"),
	perplexityApiKey: ENV_READER("PERPLEXITY_API_KEY"),
};

let webSearchConfig = { ...defaultWebSearchConfig };
if (fs.existsSync(WEB_SEARCH_FILE)) {
	try {
		const raw = fs.readFileSync(WEB_SEARCH_FILE, "utf-8");
		webSearchConfig = { ...defaultWebSearchConfig, ...JSON.parse(raw) };
	} catch {
		// keep defaults
	}
}
fs.writeFileSync(
	WEB_SEARCH_FILE,
	JSON.stringify(webSearchConfig, null, 2),
	"utf-8",
);
console.log(`[+] Configured ${WEB_SEARCH_FILE}`);

// ---------------------------------------------------------------------------
// 3b. agent-browser-native config (~/.pi/config/pi-agent-browser-native/config.json)
//     Enables the optional agent_browser_web_search companion tool using the same
//     EXA / BRAVE keys from ~/.pi/.env. Global user config only — project/override
//     layers are never touched.
// ---------------------------------------------------------------------------
const AB_CONFIG_DIR = path.join(PI_DIR, "config", "pi-agent-browser-native");
const AB_CONFIG_FILE = path.join(AB_CONFIG_DIR, "config.json");
fs.mkdirSync(AB_CONFIG_DIR, { recursive: true });

const defaultAbConfig = {
	version: 1,
	webSearch: {
		enabled: true,
		preferredProvider: "exa",
		exaApiKey: ENV_READER("EXA_API_KEY"),
		braveApiKey: ENV_READER("BRAVE_API_KEY"),
	},
};

let abConfig = { ...defaultAbConfig };
if (fs.existsSync(AB_CONFIG_FILE)) {
	try {
		const raw = fs.readFileSync(AB_CONFIG_FILE, "utf-8");
		const existing = JSON.parse(raw);
		abConfig = {
			...defaultAbConfig,
			...existing,
			webSearch: {
				...defaultAbConfig.webSearch,
				...(existing.webSearch || {}),
			},
		};
	} catch {
		// keep defaults
	}
}
fs.writeFileSync(AB_CONFIG_FILE, JSON.stringify(abConfig, null, 2), "utf-8");
console.log(
	`[+] Configured ${AB_CONFIG_FILE} (agent_browser_web_search companion)`,
);

// ---------------------------------------------------------------------------
// 4. Safe Re-runnable Auth File (~/.pi/agent/auth.json)
// ---------------------------------------------------------------------------
const AUTH_FILE = path.join(AGENT_DIR, "auth.json");
let authConfig = {
	opencode: { type: "api_key", key: "" },
	"9router": { type: "api_key", key: "" },
};

if (fs.existsSync(AUTH_FILE)) {
	try {
		const raw = fs.readFileSync(AUTH_FILE, "utf-8");
		const existingAuth = JSON.parse(raw);
		authConfig = { ...authConfig, ...existingAuth };
	} catch {
		// keep defaults
	}
}
fs.writeFileSync(AUTH_FILE, JSON.stringify(authConfig, null, 2), "utf-8");
console.log(`[+] Configured ${AUTH_FILE} (preserved existing tokens)`);

// ---------------------------------------------------------------------------
// 5. Safe Re-runnable Settings (~/.pi/agent/settings.json)
// ---------------------------------------------------------------------------
const SETTINGS_FILE = path.join(AGENT_DIR, "settings.json");

// NOTE: pi-agent-browser-native is intentionally listed as a plain string here.
// Its package manifest already declares the agent-browser extension entry point,
// so a plain source loads the `agent_browser` tool with no manual filter needed.
// (An explicit `-dist/...` filter is what previously DISABLED the tool.)
const requiredPackages = [
	"npm:pi-mcp-adapter",
	"npm:pi-web-access",
	"npm:pi-subagents",
	"npm:pi-lens",
	"npm:@juicesharp/rpiv-ask-user-question",
	"npm:@ff-labs/pi-fff",
	"npm:@juicesharp/rpiv-todo",
	"npm:pi-agent-browser-native",
	"npm:pi-rtk-optimizer",
	"npm:pi-sidebar-tui",
	"npm:opencode-pi",
	"extensions/9router-sync.ts",
];

const OLD_HOOK_SOURCE = "extensions/9router-discovery.ts"; // migrated away
const OLD_HOOK_FILE = path.join(EXT_DIR, "9router-discovery.ts");

let settingsConfig = {
	lastChangelogVersion: "0.83.0",
	theme: "dark",
	defaultProvider: "opencode",
	defaultModel: "deepseek-v4-flash-free",
	defaultThinkingLevel: "max",
	showHardwareCursor: false,
	showCacheMissNotices: true,
	defaultProjectTrust: "always",
	doubleEscapeAction: "tree",
	enableInstallTelemetry: false,
	treeFilterMode: "default",
	packages: [],
};

if (fs.existsSync(SETTINGS_FILE)) {
	try {
		const raw = fs.readFileSync(SETTINGS_FILE, "utf-8");
		settingsConfig = { ...settingsConfig, ...JSON.parse(raw) };
	} catch {
		// keep defaults
	}
}

if (!Array.isArray(settingsConfig.packages)) {
	settingsConfig.packages = [];
}

// -- Migrate: drop the old always-on hook entry, add the sanitizer+sync one --
settingsConfig.packages = settingsConfig.packages.filter((p) => {
	const key = typeof p === "string" ? p : p?.source;
	if (key === OLD_HOOK_SOURCE) {
		console.log(`[~] Removed legacy hook package entry: ${key}`);
		return false;
	}
	return true;
});

// -- Deduplicate required packages (string or object source identity) --
for (const reqPkg of requiredPackages) {
	const reqKey = typeof reqPkg === "string" ? reqPkg : reqPkg.source;
	const exists = settingsConfig.packages.some((p) => {
		const existingKey = typeof p === "string" ? p : p.source;
		return existingKey === reqKey;
	});
	if (!exists) {
		settingsConfig.packages.push(reqPkg);
	}
}

fs.writeFileSync(
	SETTINGS_FILE,
	JSON.stringify(settingsConfig, null, 2),
	"utf-8",
);
console.log(
	`[+] Configured ${SETTINGS_FILE} (packages merged without duplicates)`,
);

// -- Remove the old hook extension file if it still exists --
if (fs.existsSync(OLD_HOOK_FILE)) {
	try {
		fs.unlinkSync(OLD_HOOK_FILE);
		console.log(`[~] Deleted legacy hook extension: ${OLD_HOOK_FILE}`);
	} catch (err) {
		console.warn(`[!] Could not delete ${OLD_HOOK_FILE}: ${err.message}`);
	}
}

// ---------------------------------------------------------------------------
// 6. 9Router Sync + Tool-Schema Sanitizer extension
//    (~/.pi/agent/extensions/9router-sync.ts)
//    ON-DEMAND ONLY — nothing runs at Pi launch (no session_start /
//    before_agent_start / before_provider_request hooks).
//    The /9router-sync slash command:
//      - syncs the 9Router model catalog into ~/.pi/agent/models.json
//      - sanitizes registered tool schemas in place (removes enumerable
//        TypeBox metadata keys ~optional/~kind/~readonly, fixing Gemini/
//        Antigravity `HTTP 400: Unknown name "~optional"`).
// ---------------------------------------------------------------------------
const SYNC_FILE = path.join(EXT_DIR, "9router-sync.ts");
const syncCode = `// On-demand tool-schema sanitizer + 9Router model sync.
// ============================================================================
// Root cause this fixes:
//   Some tools (e.g. pi-mcp-adapter's mcpScript.timeoutMs, mcp.limit, mcp.offset)
//   build parameter properties with Type.Optional(<raw JSON>). TypeBox marks
//   those with an ENUMERABLE ~optional key, which survives JSON.stringify and
//   reaches the provider payload. Google Gemini / Antigravity rejects it with:
//     HTTP 400: Unknown name "~optional" ... Cannot find field.
//
// Fix: run /9router-sync (on demand) to sanitize registered tool schemas in
// place — deleting enumerable TypeBox metadata keys (~optional, ~kind, ~readonly)
// from every tool's parameters object — and to sync the 9Router model catalog.
// NOTHING runs at Pi launch; no session_start / before_agent_start /
// before_provider_request hooks. Everything happens only when you invoke the
// command. Run it after Pi starts (or after /reload), or any time you hit an
// "HTTP 400: Unknown name ~optional" error mid-session.
import { writeFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const PI_DIR = join(homedir(), ".pi");
const ENV_FILE = join(PI_DIR, ".env");
const MODELS_FILE = join(PI_DIR, "agent", "models.json");
const DEMO_BASE_URL = "https://your-9router-proxy-domain.com/v1";

function getEnvValue(key: string): string | null {
	if (process.env[key]) return process.env[key]!;
	if (existsSync(ENV_FILE)) {
		try {
			const content = readFileSync(ENV_FILE, "utf-8");
			const match = content.match(new RegExp(\`^\${key}=\\"?(.+?)\\"?$\`, "m"));
			if (match) return match[1].trim();
		} catch {
			// ignore
		}
	}
	return null;
}

function getApiKey(): string | null {
	const key = getEnvValue("NINE_ROUTER");
	return key && key.length > 0 ? key : null;
}

function getBaseUrl(): string {
	const url = getEnvValue("NINE_ROUTER_BASE_URL");
	return url && url !== DEMO_BASE_URL && url.length > 0 ? url : "";
}

// ---------------------------------------------------------------------------
// TypeBox metadata keys that must never reach a provider payload.
// ---------------------------------------------------------------------------
const TYPEBOX_META_KEYS = new Set(["~optional", "~kind", "~readonly"]);

function cleanSchema(obj: any): any {
	if (!obj || typeof obj !== "object") return obj;
	if (Array.isArray(obj)) {
		for (const item of obj) cleanSchema(item);
		return obj;
	}
	for (const key of TYPEBOX_META_KEYS) {
		delete obj[key];
	}
	for (const key of Object.keys(obj)) {
		const value = obj[key];
		if (value && typeof value === "object") {
			cleanSchema(value);
		}
	}
	return obj;
}

function sanitizeAllTools(pi: any) {
	try {
		const tools = typeof pi.getAllTools === "function" ? pi.getAllTools() : [];
		let count = 0;
		for (const tool of tools) {
			if (tool?.parameters) {
				cleanSchema(tool.parameters);
				count += 1;
			}
		}
		return count;
	} catch {
		return 0;
	}
}

async function sync9RouterModels(): Promise<{ ok: boolean; message: string; count?: number }> {
	const apiKey = getApiKey();
	const baseUrl = getBaseUrl();
	if (!apiKey) {
		return { ok: false, message: "NINE_ROUTER API key is not set in ~/.pi/.env" };
	}
	if (!baseUrl) {
		return {
			ok: false,
			message:
				"NINE_ROUTER_BASE_URL is not set (or still the demo placeholder). Set a real URL in ~/.pi/.env",
		};
	}

	try {
		const res = await fetch(\`\${baseUrl}/models\`, {
			headers: { Authorization: \`Bearer \${apiKey}\` },
			signal: AbortSignal.timeout(30000),
		});
		if (!res.ok) {
			return { ok: false, message: \`9Router /models returned HTTP \${res.status}\` };
		}

		const data = (await res.json()) as {
			data?: Array<{
				id: string;
				capabilities?: {
					reasoning?: boolean;
					vision?: boolean;
					contextWindow?: number;
					maxOutput?: number;
				};
			}>;
		};
		if (!data?.data || !Array.isArray(data.data) || data.data.length === 0) {
			return { ok: false, message: "9Router /models returned no models" };
		}

		const models = data.data.map((m) => {
			const caps = m.capabilities || {};
			return {
				id: m.id,
				name: \`\${m.id} (9Router)\`,
				reasoning: Boolean(caps.reasoning),
				input: caps.vision ? ["text", "image"] : ["text"],
				contextWindow: caps.contextWindow || 128000,
				maxTokens: caps.maxOutput || 16384,
			};
		});

		let currentConfig: { providers?: Record<string, unknown> } = { providers: {} };
		if (existsSync(MODELS_FILE)) {
			try {
				currentConfig = JSON.parse(readFileSync(MODELS_FILE, "utf-8")) as {
					providers?: Record<string, unknown>;
				};
			} catch {
				currentConfig = { providers: {} };
			}
		}
		if (!currentConfig.providers) currentConfig.providers = {};

		currentConfig.providers["9router"] = {
			name: "9Router Proxy",
			baseUrl: baseUrl,
			api: "openai-completions",
			apiKey: '!node -e "const fs=require(\\'fs\\'),p=require(\\'path\\'),os=require(\\'os\\');try{const c=fs.readFileSync(p.join(os.homedir(),\\'.pi\\',\\'.env\\'),\\'utf8\\'),m=c.match(/NINE_ROUTER=(.+)/);if(m)console.log(m[1].trim().replace(/^[\\\\\\'\\\\\\"]|[\\\\\\'\\\\\\"]$/g,\\'\\'));}catch{}"',
			compat: {
				supportsDeveloperRole: false,
			},
			models: models,
		};

		writeFileSync(MODELS_FILE, JSON.stringify(currentConfig, null, 2), "utf-8");
		return { ok: true, message: \`Synced \${models.length} 9Router models to \${MODELS_FILE}\`, count: models.length };
	} catch (err) {
		return { ok: false, message: \`9Router sync failed: \${err instanceof Error ? err.message : String(err)}\` };
	}
}

export default function (pi: any) {
	// On-demand only: NO hooks run at Pi launch. Nothing happens until you
	// invoke /9router-sync. That command syncs the 9Router model catalog AND
	// sanitizes registered tool schemas in place (removing enumerable TypeBox
	// metadata keys like ~optional that break Gemini/Antigravity). Run it after
	// Pi starts (or after /reload), or any time you hit an
	// "HTTP 400: Unknown name ~optional" error mid-session.
	pi.registerCommand("9router-sync", {
		description:
			"Sync 9Router models from NINE_ROUTER_BASE_URL into models.json and sanitize tool schemas",
		handler: async (args: string, ctx: any) => {
			const result = await sync9RouterModels();
			const sanitized = sanitizeAllTools(pi);
			const message = result.ok
				? \`\${result.message} | sanitized \${sanitized} tool schemas\`
				: result.message;
			try {
				ctx?.ui?.notify?.(message, result.ok ? "info" : "error");
			} catch {
				// no TUI available (headless/rpc) — fall back to stdout
			}
			return message;
		},
	});
}
`;

fs.writeFileSync(SYNC_FILE, syncCode, "utf-8");
console.log(
	`[+] Wrote on-demand command extension ${SYNC_FILE} (invoke with /9router-sync)`,
);

// ---------------------------------------------------------------------------
// 7. rtk binary — auto-install if missing (Rust token killer)
// ---------------------------------------------------------------------------
function ensureRtk() {
	if (NO_INSTALL) {
		console.log("[i] Skipping rtk install (--no-install)");
		return;
	}
	const existing = commandOnPath("rtk");
	if (existing) {
		console.log(`[=] rtk already available: ${existing}`);
		return;
	}

	console.log("[+] rtk binary not found — installing...");
	if (!TARGET_IS_WINDOWS) {
		// POSIX (Linux / macOS / WSL): official installer, checksum-verified, -> ~/.local/bin
		const ok = tryRun(
			"curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh",
		);
		if (ok && fs.existsSync(path.join(LOCAL_BIN, "rtk"))) {
			console.log(`[+] rtk installed to ${LOCAL_BIN}`);
		} else {
			console.warn(
				"[!] Official rtk installer failed — trying direct GitHub release download...",
			);
			if (!installRtkFromGitHub()) {
				console.warn(
					"[!] rtk could not be installed automatically. Manual install:\n" +
						"    curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh",
				);
				return;
			}
		}
	} else {
		if (!installRtkFromGitHub()) {
			console.warn(
				"[!] rtk could not be installed automatically. Manual install:\n" +
					"    1. Download rtk-x86_64-pc-windows-msvc.zip from https://github.com/rtk-ai/rtk/releases\n" +
					"    2. Extract rtk.exe to %USERPROFILE%\\.local\\bin",
			);
			return;
		}
	}

	// make sure future shells see ~/.local/bin
	ensureLocalBinOnPath();
}

function installRtkFromGitHub() {
	try {
		const repo = "rtk-ai/rtk";
		const res = child_process.execSync(
			`curl -fsSL -H "Accept: application/vnd.github+json" -H "User-Agent: setup-pi-agent" https://api.github.com/repos/${repo}/releases/latest`,
			{ stdio: ["ignore", "pipe", "ignore"], maxBuffer: 10 * 1024 * 1024 },
		);
		const release = JSON.parse(String(res));
		const tag = release.tag_name;
		if (!tag) return false;

		let assetName;
		if (TARGET_IS_WINDOWS) {
			assetName = `rtk-x86_64-pc-windows-msvc.zip`;
		} else if (process.platform === "darwin") {
			assetName = `rtk-${process.arch === "arm64" ? "aarch64" : "x86_64"}-apple-darwin.tar.gz`;
		} else {
			// linux / wsl
			assetName =
				process.arch === "arm64"
					? "rtk-aarch64-unknown-linux-gnu.tar.gz"
					: "rtk-x86_64-unknown-linux-musl.tar.gz";
		}

		const url = `https://github.com/${repo}/releases/download/${tag}/${assetName}`;
		// When provisioning Windows from WSL, the temp dir must be visible to
		// Windows (PowerShell Expand-Archive can't reliably read \\wsl.localhost
		// UNC paths). Stage in TARGET_HOME/.pi/.tmp so it maps to a real C: path.
		const stagingRoot =
			TARGET_IS_WINDOWS && !HOST_IS_WINDOWS
				? path.join(TARGET_HOME, ".pi", ".tmp")
				: os.tmpdir();
		fs.mkdirSync(stagingRoot, { recursive: true });
		const tmpDir = fs.mkdtempSync(path.join(stagingRoot, "rtk-install-"));
		const archive = path.join(tmpDir, assetName);
		try {
			console.log(`[+] Downloading ${url}`);
			child_process.execSync(`curl -fsSL "${url}" -o "${archive}"`, {
				stdio: ["ignore", "inherit", "ignore"],
			});

			fs.mkdirSync(LOCAL_BIN, { recursive: true });

			if (TARGET_IS_WINDOWS) {
				// PowerShell Expand-Archive (no third-party unzip dependency). The
				// archive lives in a Windows-visible staging dir; pass Windows-style paths.
				const dest = path.join(tmpDir, "extracted");
				fs.mkdirSync(dest, { recursive: true });
				const ok = runWindowsPowerShell(
					`Expand-Archive -Path '${toWinPath(archive)}' -DestinationPath '${toWinPath(dest)}' -Force`,
				);
				if (!ok) return false;
				const exe = findFileRecursive(dest, "rtk.exe");
				if (!exe) return false;
				fs.copyFileSync(exe, path.join(LOCAL_BIN, "rtk.exe"));
			} else {
				child_process.execSync(`tar -xzf "${archive}" -C "${tmpDir}"`, {
					stdio: ["ignore", "inherit", "ignore"],
				});
				const bin = findFileRecursive(tmpDir, "rtk");
				if (!bin) return false;
				fs.copyFileSync(bin, path.join(LOCAL_BIN, "rtk"));
				try {
					fs.chmodSync(path.join(LOCAL_BIN, "rtk"), 0o755);
				} catch {
					// ignore
				}
			}

			console.log(`[+] rtk installed to ${LOCAL_BIN}`);
			return true;
		} finally {
			fs.rmSync(tmpDir, { recursive: true, force: true });
		}
	} catch (err) {
		console.warn(
			`[!] rtk GitHub install failed: ${err instanceof Error ? err.message : String(err)}`,
		);
		return false;
	}
}

function findFileRecursive(dir, name) {
	if (!fs.existsSync(dir)) return null;
	const entries = fs.readdirSync(dir, { withFileTypes: true });
	for (const entry of entries) {
		const full = path.join(dir, entry.name);
		if (entry.isFile() && entry.name === name) return full;
		if (entry.isDirectory()) {
			const found = findFileRecursive(full, name);
			if (found) return found;
		}
	}
	return null;
}

function ensureLocalBinOnPath() {
	if (TARGET_IS_WINDOWS) {
		// Add to the Windows user PATH (affects new terminals). Idempotent.
		const ps = [
			`$p = [Environment]::GetEnvironmentVariable('Path','User')`,
			`if ($p -notlike '*\\.local\\bin*') { [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';' + [Environment]::GetFolderPath('UserProfile') + '\\.local\\bin'), 'User') }`,
		].join("; ");
		const ok = runWindowsPowerShell(ps);
		if (ok) {
			console.log(
				`[+] Added ${LOCAL_BIN} to Windows user PATH (new terminals only)`,
			);
		} else {
			console.warn(
				`[!] Please add ${LOCAL_BIN} to your Windows user PATH manually.`,
			);
		}
		return;
	}

	if (pathContains(LOCAL_BIN)) {
		console.log(`[=] ${LOCAL_BIN} already on PATH`);
		return;
	}

	// POSIX: append idempotently to the detected shell rc files
	const exportLine = `export PATH="$HOME/.local/bin:$PATH"`;
	const rcFiles = [];
	if (process.env.SHELL?.includes("zsh"))
		rcFiles.push(path.join(os.homedir(), ".zshrc"));
	if (process.env.SHELL?.includes("fish"))
		rcFiles.push(path.join(os.homedir(), ".config", "fish", "config.fish"));
	if (process.env.SHELL?.includes("bash"))
		rcFiles.push(path.join(os.homedir(), ".bashrc"));
	rcFiles.push(path.join(os.homedir(), ".bashrc"));
	rcFiles.push(path.join(os.homedir(), ".profile"));

	for (const rc of rcFiles) {
		if (!fs.existsSync(rc)) continue;
		const content = fs.readFileSync(rc, "utf-8");
		if (content.includes(".local/bin")) continue;
		fs.appendFileSync(rc, `\n${exportLine}\n`);
		console.log(`[+] Added PATH export to ${rc}`);
		return;
	}
	// no existing rc file — create .profile
	const profile = path.join(os.homedir(), ".profile");
	if (!fs.existsSync(profile)) {
		fs.writeFileSync(
			profile,
			`# added by setup-pi-agent.js\n${exportLine}\n`,
			"utf-8",
		);
		console.log(`[+] Created ${profile} with PATH export`);
	} else {
		const content = fs.readFileSync(profile, "utf-8");
		if (!content.includes(".local/bin")) {
			fs.appendFileSync(profile, `\n${exportLine}\n`);
			console.log(`[+] Added PATH export to ${profile}`);
		}
	}
}

ensureRtk();

// ---------------------------------------------------------------------------
// 8. agent-browser — CLI + Chrome for Testing + ffmpeg
// ---------------------------------------------------------------------------
function ensureAgentBrowser() {
	if (NO_INSTALL) {
		console.log("[i] Skipping agent-browser setup (--no-install)");
		return;
	}
	// 8a. CLI
	const cli = commandOnPath("agent-browser");
	if (!cli) {
		console.log(
			"[+] agent-browser CLI not found — installing via npm (global)...",
		);
		const ok = targetTryRun("npm install -g agent-browser");
		if (!ok || !commandOnPath("agent-browser")) {
			console.warn(
				"[!] agent-browser CLI install failed. Manual: npm install -g agent-browser",
			);
			return;
		}
		console.log("[+] agent-browser CLI installed");
	} else {
		console.log(`[=] agent-browser CLI already available: ${cli}`);
	}

	// 8b. Chrome for Testing (downloaded by `agent-browser install`)
	const browsersDir = path.join(TARGET_HOME, ".agent-browser", "browsers");
	const chromePresent = (() => {
		if (!fs.existsSync(browsersDir)) return false;
		try {
			const entries = fs.readdirSync(browsersDir);
			return entries.some((e) => /^chrome-/.test(e));
		} catch {
			return false;
		}
	})();

	if (!chromePresent) {
		console.log(
			"[+] Chrome for Testing missing — running 'agent-browser install' (one-time download)",
		);
		const ok = targetTryRun("agent-browser install");
		if (!ok) {
			console.warn(
				"[!] 'agent-browser install' failed. On Linux/WSL you may need system deps:\n" +
					"    sudo agent-browser install --with-deps   (or)   agent-browser doctor --fix",
			);
		} else {
			console.log("[+] Chrome for Testing installed");
		}
	} else {
		console.log("[=] Chrome for Testing already present");
	}

	// 8c. ffmpeg (needed only for `record stop` WebM encoding)
	if (!commandOnPath("ffmpeg")) {
		console.warn(
			"[!] ffmpeg not found — browser screen recording ('record stop') needs it.\n" +
				"    Linux/WSL: sudo apt install ffmpeg | macOS: brew install ffmpeg | Windows: winget install ffmpeg",
		);
	} else {
		console.log("[=] ffmpeg available (screen recording OK)");
	}
}

ensureAgentBrowser();

// ---------------------------------------------------------------------------
// 9. Package Installation (pi install keeps npm packages 100% untouched)
// ---------------------------------------------------------------------------
const installPkgs = [
	"npm:pi-mcp-adapter",
	"npm:pi-web-access",
	"npm:pi-subagents",
	"npm:pi-lens",
	"npm:@juicesharp/rpiv-ask-user-question",
	"npm:@ff-labs/pi-fff",
	"npm:@juicesharp/rpiv-todo",
	"npm:pi-agent-browser-native",
	"npm:pi-rtk-optimizer",
	"npm:pi-sidebar-tui",
	"npm:opencode-pi",
];

console.log("-> Checking package installation...");
if (NO_INSTALL) {
	console.log("[i] Skipping pi install (--no-install)");
} else {
	if (TARGET_IS_WINDOWS) {
		// Windows target: pi CLI itself must exist on the Windows side.
		if (!commandOnPath("pi")) {
			console.log(
				"[+] pi CLI not found on Windows target — installing pi globally...",
			);
			const ok = targetTryRun("npm install -g @earendil-works/pi-coding-agent");
			if (!ok || !commandOnPath("pi")) {
				console.warn(
					"[!] Could not install pi on the Windows target. Manual: npm install -g @earendil-works/pi-coding-agent",
				);
			}
		}
	}
	for (const pkg of installPkgs) {
		try {
			targetRun(`pi install ${pkg}`);
		} catch {
			console.warn(`[!] Warning: Could not install ${pkg}`);
		}
	}
}

// ---------------------------------------------------------------------------
// 10. Final summary
// ---------------------------------------------------------------------------
console.log("=============================================");
console.log("   Setup Finished Successfully!              ");
console.log("---------------------------------------------");
console.log("  Next steps:");
console.log("    1. Restart Pi (or use /reload).");
console.log("    2. The 9Router model list is NOT synced automatically.");
console.log("       Run the slash command:  /9router-sync");
console.log(
	"       (Gemini tool-schema sanitizer runs automatically — no step needed.)",
);
console.log("    3. agent_browser tool: ask for a browser action, e.g.");
console.log('       "Use the agent_browser tool to open https://example.com".');
console.log("=============================================");
