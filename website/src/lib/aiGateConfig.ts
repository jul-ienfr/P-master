import {
  createDefaultJevGateConfig,
  normalizeJevGateConfig,
  toPersistableJevGateConfig,
  type ConfigLabJevConfig,
} from "./jevGateConfig";

export type AiGateProvider = "jev" | "djev" | "auto";

export type AiGatePresetId = "lan" | "offline" | "cloud";

export type AiGateMode = "off" | "observer" | "enforcing";

export interface AiGateDjevConfig {
  baseUrl: string;
  model: string;
  apiKeyEnv: string;
  timeoutS: number;
  mode: AiGateMode;
  lanUrl: string;
  cloudUrl: string;
  cloudFallback: boolean;
  offlineMode: boolean;
  minUpgradeConfidence: number;
  minDowngradeConfidence: number;
  riskyThreshold: number;
}

export interface AiGateConfig {
  provider: AiGateProvider;
  offlineMode: boolean;
  cloudFallback: boolean;
  jev: ConfigLabJevConfig;
  djev: AiGateDjevConfig;
}

export const AI_GATE_STORAGE_KEY = "pokermaster:v2:ai-gate-config";
export const AI_GATE_DEFAULT_DJEV_MODEL = "jev-1.13.0";
export const AI_GATE_DEFAULT_DJEV_BASE_URL = "https://api.typesafe.ai/v1/systemone";
export const AI_GATE_DEFAULT_DJEV_CLOUD_URL = "https://api.typesafe.ai/v1/systemone";
export const AI_GATE_DEFAULT_DJEV_LAN_URL = "http://127.0.0.1:4000";
export const AI_GATE_DEFAULT_API_KEY_ENV = "TYPESAFE_API_KEY";
export const AI_GATE_DEFAULT_LOOPBACK_PROXY = "http://127.0.0.1:4000";

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

function asBool(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
  }
  if (typeof value === "number") {
    return value !== 0;
  }
  return fallback;
}

// Comme normalize_jev_gate_config : sous le plancher -> repli sur le défaut.
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

/** True si l'URL vise le loopback (127.0.0.1, localhost, ::1). */
export function isLoopbackUrl(url: unknown): boolean {
  const raw = typeof url === "string" ? url.trim() : "";
  if (!raw) {
    return false;
  }
  try {
    const parsed = new URL(raw.includes("://") ? raw : `http://${raw}`);
    const host = parsed.hostname.replace(/^\[|\]$/g, "").toLowerCase();
    return host === "127.0.0.1" || host === "localhost" || host === "::1";
  } catch {
    return false;
  }
}

export function createDefaultAiGateDjevConfig(): AiGateDjevConfig {
  return {
    baseUrl: AI_GATE_DEFAULT_DJEV_LAN_URL,
    model: AI_GATE_DEFAULT_DJEV_MODEL,
    apiKeyEnv: AI_GATE_DEFAULT_API_KEY_ENV,
    timeoutS: 5.0,
    mode: "observer",
    lanUrl: AI_GATE_DEFAULT_DJEV_LAN_URL,
    cloudUrl: AI_GATE_DEFAULT_DJEV_CLOUD_URL,
    cloudFallback: false,
    offlineMode: true,
    minUpgradeConfidence: 0.3,
    minDowngradeConfidence: 0.6,
    riskyThreshold: 0.7,
  };
}

export function createDefaultAiGateConfig(): AiGateConfig {
  return {
    provider: "jev",
    offlineMode: true,
    cloudFallback: false,
    jev: createDefaultJevGateConfig(),
    djev: createDefaultAiGateDjevConfig(),
  };
}

function normalizeAiGateDjev(rawValue: unknown, defaults: AiGateDjevConfig): AiGateDjevConfig {
  const raw = asRecord(rawValue);
  const modeRaw = asNonEmptyString(raw.mode, defaults.mode).toLowerCase();
  const mode: AiGateMode =
    modeRaw === "off" || modeRaw === "enforcing" ? modeRaw : "observer";

  return {
    baseUrl: asNonEmptyString(raw.baseUrl ?? raw.base_url, defaults.baseUrl),
    model: asNonEmptyString(raw.model, defaults.model),
    // Nom de variable d'environnement uniquement, jamais la valeur.
    apiKeyEnv: asNonEmptyString(raw.apiKeyEnv ?? raw.api_key_env, defaults.apiKeyEnv),
    timeoutS: asBoundedNumber(raw.timeoutS ?? raw.timeout_s, 0.5, defaults.timeoutS),
    mode,
    lanUrl: asNonEmptyString(raw.lanUrl ?? raw.lan_url, defaults.lanUrl),
    cloudUrl: asNonEmptyString(raw.cloudUrl ?? raw.cloud_url, defaults.cloudUrl),
    cloudFallback: asBool(raw.cloudFallback ?? raw.cloud_fallback, defaults.cloudFallback),
    offlineMode: asBool(raw.offlineMode ?? raw.offline_mode, defaults.offlineMode),
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
  };
}

/**
 * Normalisation ai_gate validée contre docs/ai_gate.schema.json.
 * Garde offline : WAN refusée — cloud fallbacks tombés, Djev marqué offline,
 * base Jev non-loopback rebasculée sur le proxy loopback (miroir Python
 * ai_router._auto). La base Djev cloud est conservée telle quelle mais n'est
 * jamais appelée en offline (garde query-time côté djev_gate).
 */
export function normalizeAiGateConfig(rawValue: unknown): AiGateConfig {
  const raw = asRecord(rawValue);
  const defaults = createDefaultAiGateConfig();

  const providerRaw = asNonEmptyString(raw.provider, defaults.provider).toLowerCase();
  const provider: AiGateProvider =
    providerRaw === "jev" || providerRaw === "djev" ? providerRaw : "auto";

  const offlineMode = asBool(raw.offlineMode ?? raw.offline_mode, defaults.offlineMode);
  const djev = normalizeAiGateDjev(raw.djev, defaults.djev);
  const jev = normalizeJevGateConfig(
    (raw.jev as unknown) ?? (raw.jev_gate as unknown) ?? {}
  );

  const next: AiGateConfig = {
    provider,
    offlineMode,
    cloudFallback: asBool(raw.cloudFallback ?? raw.cloud_fallback, defaults.cloudFallback),
    jev,
    djev,
  };

  if (next.offlineMode) {
    // Offline strict : aucun egress WAN.
    next.cloudFallback = false;
    next.djev.cloudFallback = false;
    next.djev.offlineMode = true;
    if (!isLoopbackUrl(next.jev.baseUrl)) {
      next.jev.baseUrl = AI_GATE_DEFAULT_LOOPBACK_PROXY;
    }
  }

  return next;
}

export const AI_GATE_PRESETS: AiGatePresetId[] = ["lan", "offline", "cloud"];

/**
 * Presets config-lab : LAN prioritaire / Offline strict / Cloud fallback autorisé.
 * Lock : LAN prioritaire + Offline strict par défaut, cloud jamais proposé
 * (le preset "cloud" reste disponible explicitement mais la config par défaut
 *  est jev + offline strict, cloud désactivé par choix).
 * Appliqués puis renormalisés (les gardes offline s'appliquent toujours).
 */
export function applyAiGatePreset(config: AiGateConfig, preset: AiGatePresetId): AiGateConfig {
  const lanUrl = config.djev.lanUrl.trim() || AI_GATE_DEFAULT_DJEV_LAN_URL;
  const cloudUrl = config.djev.cloudUrl.trim() || AI_GATE_DEFAULT_DJEV_CLOUD_URL;

  switch (preset) {
    case "lan":
      return normalizeAiGateConfig({
        ...config,
        provider: "auto",
        offlineMode: false,
        cloudFallback: false,
        djev: { ...config.djev, baseUrl: lanUrl, cloudFallback: false, offlineMode: false },
      });
    case "offline":
      return normalizeAiGateConfig({
        ...config,
        provider: "auto",
        offlineMode: true,
        cloudFallback: false,
        djev: { ...config.djev, cloudFallback: false, offlineMode: true },
      });
    case "cloud":
      return normalizeAiGateConfig({
        ...config,
        provider: "auto",
        offlineMode: false,
        cloudFallback: true,
        djev: { ...config.djev, baseUrl: cloudUrl, cloudFallback: true, offlineMode: false },
      });
    default:
      return normalizeAiGateConfig(config);
  }
}

export function toPersistableAiGateConfig(config: AiGateConfig): Record<string, unknown> {
  return {
    provider: config.provider,
    offline_mode: config.offlineMode,
    cloud_fallback: config.cloudFallback,
    jev: toPersistableJevGateConfig(config.jev),
    djev: {
      base_url: config.djev.baseUrl,
      model: config.djev.model,
      // Nom de var uniquement — jamais la valeur de clé.
      api_key_env: config.djev.apiKeyEnv,
      timeout_s: config.djev.timeoutS,
      mode: config.djev.mode,
      lan_url: config.djev.lanUrl,
      cloud_url: config.djev.cloudUrl,
      cloud_fallback: config.djev.cloudFallback,
      offline_mode: config.djev.offlineMode,
      min_upgrade_confidence: config.djev.minUpgradeConfidence,
      min_downgrade_confidence: config.djev.minDowngradeConfidence,
      risky_threshold: config.djev.riskyThreshold,
    },
  };
}

function loadStoredAiGateConfig(): AiGateConfig | null {
  if (typeof localStorage === "undefined") {
    return null;
  }

  try {
    const rawValue = localStorage.getItem(AI_GATE_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }
    return normalizeAiGateConfig(JSON.parse(rawValue));
  } catch {
    return null;
  }
}

function persistStoredAiGateConfig(config: AiGateConfig): void {
  if (typeof localStorage === "undefined") {
    return;
  }

  try {
    localStorage.setItem(AI_GATE_STORAGE_KEY, JSON.stringify(toPersistableAiGateConfig(config)));
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

export async function loadAiGateConfig(): Promise<AiGateConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("get_ai_gate_config");
      const normalized = normalizeAiGateConfig(response);
      persistStoredAiGateConfig(normalized);
      return normalized;
    }
  } catch {
    // Fall back to browser storage below.
  }

  return loadStoredAiGateConfig() ?? createDefaultAiGateConfig();
}

export async function persistAiGateConfig(config: AiGateConfig): Promise<AiGateConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("set_ai_gate_config", {
        config: toPersistableAiGateConfig(config),
      });
      const normalized = normalizeAiGateConfig(response);
      persistStoredAiGateConfig(normalized);
      return normalized;
    }
  } catch {
    // Fall back to browser storage below.
  }

  const normalized = normalizeAiGateConfig(config);
  persistStoredAiGateConfig(normalized);
  return normalized;
}
