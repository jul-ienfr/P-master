import type {
  ConfigLabJevBackend,
  ConfigLabJevDeployment,
  ConfigLabJevMode,
  ConfigLabJevMultimodalMode,
  ConfigLabJevUsageName,
} from "./configLab";

export interface ConfigLabJevLanConfig {
  baseUrl: string;
  model: string;
  timeoutTextS: number;
  timeoutImageS: number;
  apiKeyEnv: string;
}

export interface ConfigLabJevMultimodalConfig {
  enabled: boolean;
  mode: ConfigLabJevMultimodalMode;
  maxImages: number;
  cropSizePx: number;
  jpegQuality: number;
}

export interface ConfigLabJevUsageEntry {
  enabled: boolean;
  timeoutS: number;
}

export type ConfigLabJevUsages = Record<ConfigLabJevUsageName, ConfigLabJevUsageEntry>;

export interface ConfigLabJevConfig {
  baseUrl: string;
  model: string;
  timeoutS: number;
  mode: ConfigLabJevMode;
  minUpgradeConfidence: number;
  minDowngradeConfidence: number;
  riskyThreshold: number;
  deployment: ConfigLabJevDeployment;
  backend: ConfigLabJevBackend;
  lan: ConfigLabJevLanConfig;
  multimodal: ConfigLabJevMultimodalConfig;
  usages: ConfigLabJevUsages;
}

const JEV_GATE_STORAGE_KEY = "pokermaster:v2:jev-gate-config";

export const JEV_GATE_USAGES: ConfigLabJevUsageName[] = [
  "autolabel",
  "judge",
  "report",
  "attention",
  "tier_budget",
  "drift",
];

type UnknownRecord = Record<string, unknown>;
type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

function asRecord(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : {};
}

function asNonEmptyString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

function asFiniteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

// Comme normalize_jev_gate_config (Rust) : sous le plancher -> repli sur le
// défaut, pas clamp au plancher. Un timeout négatif ou nul n'a aucun sens.
function asBoundedNumber(value: unknown, min: number, fallback: number): number {
  const parsed = asFiniteNumber(value, fallback);
  return parsed >= min ? parsed : fallback;
}

function clampConfidence(value: number, fallback: number): number {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(1, Math.max(0, value));
}

function clampInt(value: number, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, Math.round(value)));
}

export function createDefaultJevGateConfig(): ConfigLabJevConfig {
  const usages = {} as ConfigLabJevUsages;
  for (const name of JEV_GATE_USAGES) {
    usages[name] = { enabled: true, timeoutS: 15 };
  }

  return {
    baseUrl: "http://127.0.0.1:4000",
    model: "jev-1.13-free",
    timeoutS: 0.8,
    mode: "observer",
    minUpgradeConfidence: 0.3,
    minDowngradeConfidence: 0.6,
    riskyThreshold: 0.7,
    deployment: "single",
    backend: "cloud",
    lan: {
      baseUrl: "",
      model: "qwen2.5-vl-3b",
      timeoutTextS: 1.0,
      timeoutImageS: 15.0,
      apiKeyEnv: "POKER_JEV_LAN_KEY",
    },
    multimodal: {
      enabled: false,
      mode: "text_only",
      maxImages: 3,
      cropSizePx: 160,
      jpegQuality: 80,
    },
    usages,
  };
}

function normalizeUsageEntry(rawValue: unknown, fallback: ConfigLabJevUsageEntry): ConfigLabJevUsageEntry {
  const raw = asRecord(rawValue);
  return {
    enabled: typeof raw.enabled === "boolean" ? raw.enabled : fallback.enabled,
    timeoutS: asBoundedNumber(raw.timeoutS ?? raw.timeout_s, 0.1, fallback.timeoutS),
  };
}

function normalizeUsages(rawValue: unknown, defaults: ConfigLabJevUsages): ConfigLabJevUsages {
  const raw = asRecord(rawValue);
  const next = { ...defaults };
  for (const name of JEV_GATE_USAGES) {
    next[name] = normalizeUsageEntry(raw[name], defaults[name]);
  }
  return next;
}

export function normalizeJevGateConfig(rawValue: unknown): ConfigLabJevConfig {
  const raw = asRecord(rawValue);
  const defaults = createDefaultJevGateConfig();
  const rawLan = asRecord(raw.lan ?? raw.lanConfig);
  const rawMultimodal = asRecord(raw.multimodal);

  const modeRaw = asNonEmptyString(raw.mode, defaults.mode).toLowerCase();
  const mode: ConfigLabJevMode =
    modeRaw === "observer" || modeRaw === "enforcing" || modeRaw === "off"
      ? modeRaw
      : defaults.mode;

  const deploymentRaw = asNonEmptyString(raw.deployment, defaults.deployment).toLowerCase();
  const deployment: ConfigLabJevDeployment =
    deploymentRaw === "dual" ? "dual" : "single";

  const backendRaw = asNonEmptyString(raw.backend, defaults.backend).toLowerCase();
  const backend: ConfigLabJevBackend =
    backendRaw === "local" || backendRaw === "auto" ? backendRaw : "cloud";

  const multimodalModeRaw = asNonEmptyString(
    rawMultimodal.mode,
    defaults.multimodal.mode
  ).toLowerCase();
  // Verrou Phase 3 : crops_live parsé mais jamais actif.
  const multimodalMode: ConfigLabJevMultimodalMode =
    multimodalModeRaw === "crops_offline"
      ? "crops_offline"
      : "text_only";
  const multimodalEnabled =
    typeof rawMultimodal.enabled === "boolean"
      ? rawMultimodal.enabled && multimodalMode !== "text_only"
      : multimodalMode !== "text_only";

  const lanBaseUrl = asNonEmptyString(
    rawLan.baseUrl ?? rawLan.base_url,
    defaults.lan.baseUrl
  );
  // dual sans URL LAN -> repli single (même garde que JevGateConfig.from_env).
  const safeDeployment = deployment === "dual" && !lanBaseUrl ? "single" : deployment;

  return {
    baseUrl: asNonEmptyString(raw.baseUrl ?? raw.base_url, defaults.baseUrl),
    model: asNonEmptyString(raw.model, defaults.model),
    timeoutS: asBoundedNumber(raw.timeoutS ?? raw.timeout_s, 0.05, defaults.timeoutS),
    mode,
    minUpgradeConfidence: clampConfidence(
      asFiniteNumber(
        raw.minUpgradeConfidence ?? raw.min_upgrade_confidence,
        defaults.minUpgradeConfidence
      ),
      defaults.minUpgradeConfidence
    ),
    minDowngradeConfidence: clampConfidence(
      asFiniteNumber(
        raw.minDowngradeConfidence ?? raw.min_downgrade_confidence,
        defaults.minDowngradeConfidence
      ),
      defaults.minDowngradeConfidence
    ),
    riskyThreshold: clampConfidence(
      asFiniteNumber(raw.riskyThreshold ?? raw.risky_threshold, defaults.riskyThreshold),
      defaults.riskyThreshold
    ),
    deployment: safeDeployment,
    backend,
    lan: {
      baseUrl: lanBaseUrl,
      model: asNonEmptyString(rawLan.model, defaults.lan.model),
      timeoutTextS: asBoundedNumber(
        rawLan.timeoutTextS ?? rawLan.timeout_text_s,
        0.05,
        defaults.lan.timeoutTextS
      ),
      timeoutImageS: asBoundedNumber(
        rawLan.timeoutImageS ?? rawLan.timeout_image_s,
        0.5,
        defaults.lan.timeoutImageS
      ),
      apiKeyEnv: asNonEmptyString(
        rawLan.apiKeyEnv ?? rawLan.api_key_env,
        defaults.lan.apiKeyEnv
      ),
    },
    multimodal: {
      enabled: multimodalEnabled,
      mode: multimodalMode,
      maxImages: clampInt(
        asFiniteNumber(
          rawMultimodal.maxImages ?? rawMultimodal.max_images,
          defaults.multimodal.maxImages
        ),
        1,
        8,
        defaults.multimodal.maxImages
      ),
      cropSizePx: clampInt(
        asFiniteNumber(
          rawMultimodal.cropSizePx ?? rawMultimodal.crop_size_px,
          defaults.multimodal.cropSizePx
        ),
        32,
        512,
        defaults.multimodal.cropSizePx
      ),
      jpegQuality: clampInt(
        asFiniteNumber(
          rawMultimodal.jpegQuality ?? rawMultimodal.jpeg_quality,
          defaults.multimodal.jpegQuality
        ),
        10,
        100,
        defaults.multimodal.jpegQuality
      ),
    },
    usages: normalizeUsages(raw.usages, defaults.usages),
  };
}

export function toPersistableJevGateConfig(config: ConfigLabJevConfig): Record<string, unknown> {
  const usages: Record<string, unknown> = {};
  for (const name of JEV_GATE_USAGES) {
    usages[name] = {
      enabled: config.usages[name].enabled,
      timeout_s: config.usages[name].timeoutS,
    };
  }

  return {
    base_url: config.baseUrl,
    model: config.model,
    timeout_s: config.timeoutS,
    mode: config.mode,
    min_upgrade_confidence: config.minUpgradeConfidence,
    min_downgrade_confidence: config.minDowngradeConfidence,
    risky_threshold: config.riskyThreshold,
    deployment: config.deployment,
    backend: config.backend,
    lan: {
      base_url: config.lan.baseUrl,
      model: config.lan.model,
      timeout_text_s: config.lan.timeoutTextS,
      timeout_image_s: config.lan.timeoutImageS,
      api_key_env: config.lan.apiKeyEnv,
    },
    multimodal: {
      enabled: config.multimodal.enabled,
      mode: config.multimodal.mode,
      max_images: config.multimodal.maxImages,
      crop_size_px: config.multimodal.cropSizePx,
      jpeg_quality: config.multimodal.jpegQuality,
    },
    usages,
  };
}

function loadStoredJevGateConfig(): ConfigLabJevConfig | null {
  if (typeof localStorage === "undefined") {
    return null;
  }

  try {
    const rawValue = localStorage.getItem(JEV_GATE_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }
    return normalizeJevGateConfig(JSON.parse(rawValue));
  } catch {
    return null;
  }
}

function persistStoredJevGateConfig(config: ConfigLabJevConfig): void {
  if (typeof localStorage === "undefined") {
    return;
  }

  try {
    localStorage.setItem(JEV_GATE_STORAGE_KEY, JSON.stringify(toPersistableJevGateConfig(config)));
  } catch {
    // Ignore storage failures and keep the config in memory only.
  }
}

async function resolveTauriInvoke(): Promise<TauriInvoke | null> {
  const globalWindow = globalThis as typeof globalThis & {
    __TAURI__?: {
      core?: { invoke?: TauriInvoke };
      invoke?: TauriInvoke;
    };
  };

  if (typeof globalWindow.__TAURI__?.core?.invoke === "function") {
    return globalWindow.__TAURI__.core.invoke;
  }

  if (typeof globalWindow.__TAURI__?.invoke === "function") {
    return globalWindow.__TAURI__.invoke;
  }

  try {
    const core = await import("@tauri-apps/api/core");
    return typeof core.invoke === "function" ? core.invoke : null;
  } catch {
    return null;
  }
}

export async function loadJevGateConfig(): Promise<ConfigLabJevConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("get_jev_gate_config");
      const normalized = normalizeJevGateConfig(response);
      persistStoredJevGateConfig(normalized);
      return normalized;
    }
  } catch {
    // Fall back to browser storage below.
  }

  return loadStoredJevGateConfig() ?? createDefaultJevGateConfig();
}

export async function persistJevGateConfig(
  config: ConfigLabJevConfig
): Promise<ConfigLabJevConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("set_jev_gate_config", {
        config: toPersistableJevGateConfig(config),
      });
      const normalized = normalizeJevGateConfig(response);
      persistStoredJevGateConfig(normalized);
      return normalized;
    }
  } catch {
    // Fall back to browser storage below.
  }

  const normalized = normalizeJevGateConfig(config);
  persistStoredJevGateConfig(normalized);
  return normalized;
}
