export interface AutoAnnotatorProviderConfig {
  id: string;
  baseUrl: string;
  model: string;
  apiKey: string;
}

/**
 * Voie Djev vision (observer / fail-open, jamais d'enforcing).
 *
 * Ajout isolé : les providers OpenAI/Groq existants sont INCHANGÉS. La voie
 * Djev est opt-in (défaut "off") et reste un observateur pur côté Python :
 * image -> LAN qwen2.5-vl-3b (loopback uniquement, clé via NOM de var d'env,
 * jamais en dur), jugement/validation bboxes -> Djev (schéma bbox + label +
 * confiance, "not stated" si illisible, calculs IoU/confiance en code).
 * Tout échec -> fail-open : boxes d'origine gardées, jamais d'exception.
 */
export interface DjevVisionObserverConfig {
  /** "observer" (opt-in) | "off" (défaut). Enforcing interdit ici. */
  mode: "observer" | "off";
  /** URL LAN loopback uniquement (ex. http://127.0.0.1:8080/v1). */
  lanUrl: string;
  /** Modèle vision LAN (défaut qwen2.5-vl-3b). */
  lanModel: string;
  /** NOM de la variable d'env portant la clé LAN (zéro clé en dur). */
  lanApiKeyEnv: string;
  /** Seuil de confiance min. appliqué en code (défaut 0.3). */
  minConfidence: number;
}

export interface AutoAnnotatorConfig {
  providers: AutoAnnotatorProviderConfig[];
  // Voie Djev opt-in : optionnel pour ne pas casser les appelants existants
  // (panneau config-lab) qui ne connaissent que les providers OpenAI/Groq.
  djevVision?: DjevVisionObserverConfig;
}

const AUTO_ANNOTATOR_STORAGE_KEY = "pokermaster:v2:auto-annotator-config";

type UnknownRecord = Record<string, unknown>;
type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

function asRecord(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function nextProviderId(index: number): string {
  return `provider_${Date.now()}_${index}`;
}

export const DEFAULT_DJEV_VISION_LAN_URL = "http://127.0.0.1:8080/v1";
export const DEFAULT_DJEV_VISION_LAN_MODEL = "qwen2.5-vl-3b";
export const DEFAULT_DJEV_VISION_LAN_KEY_ENV = "POKER_JEV_LAN_KEY";
export const DEFAULT_DJEV_VISION_MIN_CONFIDENCE = 0.3;

export function createDefaultDjevVisionConfig(): DjevVisionObserverConfig {
  return {
    mode: "off",
    lanUrl: DEFAULT_DJEV_VISION_LAN_URL,
    lanModel: DEFAULT_DJEV_VISION_LAN_MODEL,
    lanApiKeyEnv: DEFAULT_DJEV_VISION_LAN_KEY_ENV,
    minConfidence: DEFAULT_DJEV_VISION_MIN_CONFIDENCE,
  };
}

export function createDefaultAutoAnnotatorConfig(): AutoAnnotatorConfig {
  return {
    providers: [
      {
        id: "primary_1",
        baseUrl: "https://api.groq.com/openai/v1",
        model: "llama-3.2-90b-vision-preview",
        apiKey: "",
      },
      {
        id: "fallback_1",
        baseUrl: "https://api.openai.com/v1",
        model: "gpt-4o",
        apiKey: "",
      },
    ],
    djevVision: createDefaultDjevVisionConfig(),
  };
}

function asNumber(value: unknown, fallback: number): number {
  const parsed = typeof value === "string" ? Number(value) : (value as number);
  return typeof parsed === "number" && Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeDjevVisionConfig(rawValue: unknown): DjevVisionObserverConfig {
  const raw = asRecord(rawValue);
  const fallback = createDefaultDjevVisionConfig();
  const modeRaw = asString(raw.mode || raw.djev_vision_mode).toLowerCase();
  return {
    mode: modeRaw === "observer" ? "observer" : "off",
    lanUrl: asString(raw.lanUrl || raw.lan_url || raw.lanURL) || fallback.lanUrl,
    lanModel: asString(raw.lanModel || raw.lan_model) || fallback.lanModel,
    lanApiKeyEnv: asString(raw.lanApiKeyEnv || raw.lan_api_key_env) || fallback.lanApiKeyEnv,
    minConfidence: asNumber(
      raw.minConfidence ?? raw.min_confidence,
      fallback.minConfidence
    ),
  };
}
function normalizeProvider(rawValue: unknown, index: number): AutoAnnotatorProviderConfig {
  const raw = asRecord(rawValue);
  return {
    id: asString(raw.id) || nextProviderId(index),
    baseUrl: asString(raw.baseUrl || raw.base_url),
    model: asString(raw.model),
    apiKey: asString(raw.apiKey || raw.api_key),
  };
}

function normalizeAutoAnnotatorConfig(rawValue: unknown): AutoAnnotatorConfig {
  const raw = asRecord(rawValue);
  const rawProviders = Array.isArray(raw.providers) ? raw.providers : [];
  const providers = rawProviders.map((provider, index) => normalizeProvider(provider, index));
  const base = providers.length > 0
    ? { providers }
    : createDefaultAutoAnnotatorConfig();
  return {
    providers: base.providers,
    // Voie Djev opt-in (défaut off) : accepte camelCase + snake_case (Rust/Tauri).
    djevVision: normalizeDjevVisionConfig(
      raw.djevVision ?? raw.djev_vision ?? {}
    ),
  };
}

function toPersistableAutoAnnotatorConfig(config: AutoAnnotatorConfig): {
  providers: Array<Record<string, string>>;
  djev_vision: Record<string, string | number>;
} {
  return {
    providers: config.providers.map((provider) => ({
      base_url: provider.baseUrl.trim(),
      model: provider.model.trim(),
      api_key: provider.apiKey.trim(),
    })),
    // Sérialisé en snake_case pour le backend Rust (serde) + Python.
    djev_vision: {
      mode: config.djevVision?.mode ?? "off",
      lan_url: (config.djevVision?.lanUrl ?? DEFAULT_DJEV_VISION_LAN_URL).trim(),
      lan_model: (config.djevVision?.lanModel ?? DEFAULT_DJEV_VISION_LAN_MODEL).trim(),
      lan_api_key_env: (config.djevVision?.lanApiKeyEnv ?? DEFAULT_DJEV_VISION_LAN_KEY_ENV).trim(),
      min_confidence: config.djevVision?.minConfidence ?? DEFAULT_DJEV_VISION_MIN_CONFIDENCE,
    },
  };
}

function loadStoredAutoAnnotatorConfig(): AutoAnnotatorConfig | null {
  if (typeof localStorage === "undefined") {
    return null;
  }

  try {
    const rawValue = localStorage.getItem(AUTO_ANNOTATOR_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }
    return normalizeAutoAnnotatorConfig(JSON.parse(rawValue));
  } catch {
    return null;
  }
}

function persistStoredAutoAnnotatorConfig(config: AutoAnnotatorConfig): void {
  if (typeof localStorage === "undefined") {
    return;
  }

  try {
    localStorage.setItem(
      AUTO_ANNOTATOR_STORAGE_KEY,
      JSON.stringify(toPersistableAutoAnnotatorConfig(config))
    );
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

export async function loadAutoAnnotatorConfig(): Promise<AutoAnnotatorConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("get_auto_annotator_config");
      const normalized = normalizeAutoAnnotatorConfig(response);
      persistStoredAutoAnnotatorConfig(normalized);
      return normalized;
    }
  } catch {
    // Fall back to browser storage below.
  }

  return loadStoredAutoAnnotatorConfig() ?? createDefaultAutoAnnotatorConfig();
}

export async function persistAutoAnnotatorConfig(config: AutoAnnotatorConfig): Promise<AutoAnnotatorConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("set_auto_annotator_config", {
        config: toPersistableAutoAnnotatorConfig(config),
      });
      const normalized = normalizeAutoAnnotatorConfig(response);
      persistStoredAutoAnnotatorConfig(normalized);
      return normalized;
    }
  } catch {
    // Fall back to browser storage below.
  }

  persistStoredAutoAnnotatorConfig(config);
  return config;
}

