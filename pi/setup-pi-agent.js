const fs = require("fs");
const path = require("path");
const os = require("os");
const child_process = require("child_process");

console.log("=============================================");
console.log("   Pi Agent Idempotent Node Provisioner      ");
console.log("=============================================");

// 1. Directory Paths (Cross-platform via path.join & os.homedir)
const PI_DIR = path.join(os.homedir(), ".pi");
const AGENT_DIR = path.join(PI_DIR, "agent");
const EXT_DIR = path.join(AGENT_DIR, "extensions");

fs.mkdirSync(PI_DIR, { recursive: true });
fs.mkdirSync(AGENT_DIR, { recursive: true });
fs.mkdirSync(EXT_DIR, { recursive: true });

// 2. Safe Re-runnable Environment File (~/.pi/.env)
const ENV_FILE = path.join(PI_DIR, ".env");
let existingEnv = "";
if (fs.existsSync(ENV_FILE)) {
	existingEnv = fs.readFileSync(ENV_FILE, "utf-8");
}

const defaultEnvVars = {
	TAVILY_API_KEY: '""',
	NINE_ROUTER: '""',
	NINE_ROUTER_BASE_URL: '"https://your-9router-proxy-domain.com/v1"',
};

let envUpdated = false;
let newEnvContent = existingEnv;

for (const [key, placeholder] of Object.entries(defaultEnvVars)) {
	if (!new RegExp(`^\\s*${key}\\s*=`, "m").test(newEnvContent)) {
		if (newEnvContent && !newEnvContent.endsWith("\n")) {
			newEnvContent += "\n";
		}
		newEnvContent += `${key}=${placeholder}\n`;
		envUpdated = true;
	}
}

if (envUpdated || !fs.existsSync(ENV_FILE)) {
	fs.writeFileSync(ENV_FILE, newEnvContent, "utf-8");
	console.log(`[+] Updated ${ENV_FILE} (preserved existing keys)`);
} else {
	console.log(`[=] ${ENV_FILE} is up to date`);
}

// 3. Cross-platform Web Search Configuration (~/.pi/web-search.json)
const WEB_SEARCH_FILE = path.join(PI_DIR, "web-search.json");
const defaultWebSearchConfig = {
	provider: "auto",
	tavilyApiKey: '!node -e "const fs=require(\'fs\'),p=require(\'path\'),os=require(\'os\');try{const c=fs.readFileSync(p.join(os.homedir(),\'.pi\',\'.env\'),\'utf8\'),m=c.match(/TAVILY_API_KEY=(.+)/);if(m)console.log(m[1].trim().replace(/^[\\\'\\"]|[\\\'\\"]$/g,\'\'));}catch{}"',
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
fs.writeFileSync(WEB_SEARCH_FILE, JSON.stringify(webSearchConfig, null, 2), "utf-8");
console.log(`[+] Configured ${WEB_SEARCH_FILE}`);

// 4. Safe Re-runnable Auth File (~/.pi/agent/auth.json)
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

// 5. Safe Re-runnable Settings (~/.pi/agent/settings.json)
const SETTINGS_FILE = path.join(AGENT_DIR, "settings.json");
const requiredPackages = [
	"npm:pi-mcp-adapter",
	"npm:pi-web-access",
	"npm:pi-subagents",
	"npm:pi-lens",
	"npm:@juicesharp/rpiv-ask-user-question",
	"npm:@ff-labs/pi-fff",
	"npm:@juicesharp/rpiv-todo",
	{
		source: "npm:pi-agent-browser-native",
		extensions: ["-dist/extensions/agent-browser/index.js"],
	},
	"npm:pi-rtk-optimizer",
	"extensions/9router-discovery.ts",
];

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

// Deduplicate packages
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

fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settingsConfig, null, 2), "utf-8");
console.log(`[+] Configured ${SETTINGS_FILE} (packages merged without duplicates)`);

// 6. Dynamic 9Router Discovery Extension (~/.pi/agent/extensions/9router-discovery.ts)
const DISCOVERY_FILE = path.join(EXT_DIR, "9router-discovery.ts");
const discoveryCode = `import { writeFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const PI_DIR = join(homedir(), ".pi");
const ENV_FILE = join(PI_DIR, ".env");
const MODELS_FILE = join(PI_DIR, "agent", "models.json");

function getEnvValue(key: string): string | null {
	if (process.env[key]) return process.env[key]!;
	if (existsSync(ENV_FILE)) {
		try {
			const content = readFileSync(ENV_FILE, "utf-8");
			const match = content.match(new RegExp(\`^\${key}=\\\"?(.+?)\\\"?$\`, "m"));
			if (match) return match[1].trim();
		} catch {
			// ignore
		}
	}
	return null;
}

function getApiKey(): string | null {
	return getEnvValue("NINE_ROUTER");
}

function getBaseUrl(): string {
	return getEnvValue("NINE_ROUTER_BASE_URL") || "https://your-9router-proxy-domain.com/v1";
}

function cleanSchema(obj: any): any {
	if (!obj || typeof obj !== "object") return obj;
	if (Array.isArray(obj)) {
		obj.forEach(cleanSchema);
		return obj;
	}
	delete obj["~optional"];
	delete obj["~kind"];
	delete obj["~readonly"];
	for (const key of Object.keys(obj)) {
		if (obj[key] && typeof obj[key] === "object") {
			cleanSchema(obj[key]);
		}
	}
	return obj;
}

function sanitizeAllTools(pi: any) {
	try {
		const tools = typeof pi.getAllTools === "function" ? pi.getAllTools() : [];
		for (const tool of tools) {
			if (tool?.parameters) {
				cleanSchema(tool.parameters);
			}
		}
	} catch {
		// ignore
	}
}

async function sync9RouterModels() {
	const apiKey = getApiKey();
	const baseUrl = getBaseUrl();
	if (!apiKey) return;

	try {
		const res = await fetch(\`\${baseUrl}/models\`, {
			headers: { Authorization: \`Bearer \${apiKey}\` },
		});
		if (!res.ok) return;

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
		if (!data?.data || !Array.isArray(data.data)) return;

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
				currentConfig = JSON.parse(readFileSync(MODELS_FILE, "utf-8")) as { providers?: Record<string, unknown> };
			} catch {
				currentConfig = { providers: {} };
			}
		}
		if (!currentConfig.providers) currentConfig.providers = {};

		currentConfig.providers["9router"] = {
			name: "9Router Proxy",
			baseUrl: baseUrl,
			api: "openai-completions",
			apiKey: '!node -e "const fs=require(\\'fs\\'),p=require(\\'path\\'),os=require(\\'os\\');try{const c=fs.readFileSync(p.join(os.homedir(),\\'.pi\\',\\'.env\\'),\\'utf8\\'),m=c.match(/NINE_ROUTER=(.+)/);if(m)console.log(m[1].trim().replace(/^[\\\\\\\'\\\\\\"]|[\\\\\\\'\\\\\\"]$/g,\\\'\\\'));}catch{}"',
			compat: {
				supportsDeveloperRole: false
			},
			models: models,
		};

		writeFileSync(MODELS_FILE, JSON.stringify(currentConfig, null, 2), "utf-8");
	} catch {
		// silent catch
	}
}

export default function (pi: any) {
	pi.on("session_start", async () => {
		await sync9RouterModels();
		sanitizeAllTools(pi);
	});

	pi.on("before_agent_start", async () => {
		sanitizeAllTools(pi);
	});
}
`;

fs.writeFileSync(DISCOVERY_FILE, discoveryCode, "utf-8");
console.log(`[+] Updated extension ${DISCOVERY_FILE}`);

// 7. Package Installation
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
];

console.log("-> Checking package installation...");
for (const pkg of installPkgs) {
	try {
		child_process.execSync(`pi install ${pkg}`, { stdio: "inherit" });
	} catch {
		console.warn(`[!] Warning: Could not install ${pkg}`);
	}
}

console.log("=============================================");
console.log("   Setup Finished Successfully!              ");
console.log("=============================================");
