export interface AutoAnnotatorProviderConfig {
  id: string;
  baseUrl: string;
  model: string;
  apiKey: string;
}

export interface AutoAnnotatorConfig {
  providers: AutoAnnotatorProviderConfig[];
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
  return providers.length > 0 ? { providers } : createDefaultAutoAnnotatorConfig();
}

function toPersistableAutoAnnotatorConfig(config: AutoAnnotatorConfig): { providers: Array<Record<string, string>> } {
  return {
    providers: config.providers.map((provider) => ({
      base_url: provider.baseUrl.trim(),
      model: provider.model.trim(),
      api_key: provider.apiKey.trim(),
    })),
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

