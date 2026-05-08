import type { ConfigLabOcrMode, ConfigLabPayload } from "./configLab";

export type OcrConfig = ConfigLabPayload["ocr"];

const OCR_STORAGE_KEY = "pokermaster:v2:ocr-config";

type UnknownRecord = Record<string, unknown>;
type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

function asRecord(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : {};
}

function asStringArray(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value)) {
    return fallback;
  }

  const items = value.filter(
    (entry): entry is string => typeof entry === "string" && entry.trim().length > 0
  );

  return items.length > 0 ? items : fallback;
}

export function createDefaultOcrConfig(): OcrConfig {
  return {
    enabledEngines: ["surya", "easyocr"],
    mode: "consensus_amounts",
    parallel: true,
    useGpu: true,
  };
}

function normalizeOcrConfig(rawValue: unknown): OcrConfig {
  const raw = asRecord(rawValue);
  const defaults = createDefaultOcrConfig();

  return {
    enabledEngines: asStringArray(raw.enabledEngines ?? raw.enabled_engines, defaults.enabledEngines),
    mode: (typeof raw.mode === "string" && raw.mode.trim().length > 0
      ? raw.mode
      : defaults.mode) as ConfigLabOcrMode,
    parallel: typeof raw.parallel === "boolean" ? raw.parallel : defaults.parallel,
    useGpu: typeof (raw.useGpu ?? raw.use_gpu) === "boolean"
      ? Boolean(raw.useGpu ?? raw.use_gpu)
      : defaults.useGpu,
  };
}

function toPersistableOcrConfig(config: OcrConfig): Record<string, unknown> {
  return {
    enabled_engines: config.enabledEngines,
    mode: config.mode,
    parallel: config.parallel,
    use_gpu: config.useGpu,
  };
}

function loadStoredOcrConfig(): OcrConfig | null {
  if (typeof localStorage === "undefined") {
    return null;
  }

  try {
    const rawValue = localStorage.getItem(OCR_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }
    return normalizeOcrConfig(JSON.parse(rawValue));
  } catch {
    return null;
  }
}

function persistStoredOcrConfig(config: OcrConfig): void {
  if (typeof localStorage === "undefined") {
    return;
  }

  try {
    localStorage.setItem(OCR_STORAGE_KEY, JSON.stringify(toPersistableOcrConfig(config)));
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

export async function loadOcrConfig(): Promise<OcrConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("get_ocr_config");
      const normalized = normalizeOcrConfig(response);
      persistStoredOcrConfig(normalized);
      return normalized;
    }
  } catch {
    // Fall back to browser storage below.
  }

  return loadStoredOcrConfig() ?? createDefaultOcrConfig();
}

export async function persistOcrConfig(config: OcrConfig): Promise<OcrConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("set_ocr_config", {
        config: toPersistableOcrConfig(config),
      });
      const normalized = normalizeOcrConfig(response);
      persistStoredOcrConfig(normalized);
      return normalized;
    }
  } catch {
    // Fall back to browser storage below.
  }

  const normalized = normalizeOcrConfig(config);
  persistStoredOcrConfig(normalized);
  return normalized;
}
