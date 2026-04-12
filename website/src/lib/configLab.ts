export type ConfigLabSource = "tauri" | "runtime" | "offline" | "error";

export type ConfigLabStatus = "ready" | "degraded" | "offline" | "error";

export type ConfigLabRefreshMode = "load" | "refresh";

export type ConfigLabProviderMode = "openai_compatible_remote" | "openai_compatible_local" | "disabled";

export type ConfigLabPrivacyMode = "strict_local" | "redacted_remote" | "full_remote";

export interface ConfigLabRuntimeSnapshot {
  connected: boolean;
  transport: string;
  endpoint: string;
  refreshedAt: string;
  raw?: Record<string, unknown>;
}

export interface ConfigLabLlmConfig {
  enabled: boolean;
  providerMode: ConfigLabProviderMode;
  baseUrl: string;
  apiKeyRef: string;
  model: string;
  temperature: number;
  maxOutputTokens: number;
  streaming: boolean;
  rolesEnabled: string[];
  contextScopesEnabled: string[];
  privacyMode: ConfigLabPrivacyMode;
}

export interface ConfigLabSolverConfig {
  selectedPresetId: string;
  availablePresetIds: string[];
  treeCompression: string;
  timeBudgetMs: number;
  cacheEnabled: boolean;
}

export type ConfigLabOcrMode = "priority" | "fallback" | "consensus_amounts";

export interface ConfigLabOcrConfig {
  enabledEngines: string[];
  mode: ConfigLabOcrMode;
  parallel: boolean;
  useGpu: boolean;
}

export interface ConfigLabOcrStatus {
  supportedEngines: string[];
  requestedEngines: string[];
  loadedEngines: string[];
  unavailableEngines: Record<string, string>;
  mode: ConfigLabOcrMode;
  parallel: boolean;
  useGpu: boolean;
}

export interface ConfigLabBenchmarkEntry {
  id: string;
  name: string;
  status: "ready" | "running" | "queued" | "disabled";
  score: number;
  note: string;
}

export interface ConfigLabPayload {
  kind: "config_lab";
  status: ConfigLabStatus;
  source: ConfigLabSource;
  refreshedAt: string;
  runtime: ConfigLabRuntimeSnapshot;
  llm: ConfigLabLlmConfig;
  solver: ConfigLabSolverConfig;
  ocr: ConfigLabOcrConfig;
  privacy: {
    strictLocal: boolean;
    redactedRemote: boolean;
    fullRemote: boolean;
  };
  benchmarks: ConfigLabBenchmarkEntry[];
  warnings: string[];
  recommendations: string[];
  raw?: Record<string, unknown>;
}

type JsonRecord = Record<string, unknown>;

const DEFAULT_CONFIG_LAB_PAYLOAD: ConfigLabPayload = {
  kind: "config_lab",
  status: "offline",
  source: "offline",
  refreshedAt: "2026-04-11T00:00:00.000Z",
  runtime: {
    connected: false,
    transport: "offline",
    endpoint: "",
    refreshedAt: "2026-04-11T00:00:00.000Z",
  },
  llm: {
    enabled: false,
    providerMode: "disabled",
    baseUrl: "",
    apiKeyRef: "",
    model: "gpt-4.1-mini",
    temperature: 0.2,
    maxOutputTokens: 1024,
    streaming: false,
    rolesEnabled: ["analysis", "operator_assistance"],
    contextScopesEnabled: ["spot_snapshot", "decision_snapshot", "replay_summary"],
    privacyMode: "strict_local",
  },
  solver: {
    selectedPresetId: "srp_hu_100bb",
    availablePresetIds: ["srp_hu_100bb", "3bp_hu_100bb", "turn_probe_hu", "river_jam_low_spr"],
    treeCompression: "balanced",
    timeBudgetMs: 2500,
    cacheEnabled: true,
  },
  ocr: {
    enabledEngines: ["doctr"],
    mode: "consensus_amounts",
    parallel: true,
    useGpu: true,
  },
  privacy: {
    strictLocal: true,
    redactedRemote: false,
    fullRemote: false,
  },
  benchmarks: [
    {
      id: "cl-001",
      name: "PokerKit replay oracle",
      status: "ready",
      score: 0.98,
      note: "Use as the default rules and replay validation target.",
    },
    {
      id: "cl-002",
      name: "RLCard offline lab",
      status: "ready",
      score: 0.84,
      note: "Use for comparative policy runs and seedable experiments.",
    },
    {
      id: "cl-003",
      name: "OpenAI-format copilot",
      status: "disabled",
      score: 0.71,
      note: "Enabled only when the operator opts in from the GUI.",
    },
  ],
  warnings: [
    "Offline fallback payload in use.",
    "No configuration endpoint was available during load.",
  ],
  recommendations: [
    "Keep strict-local privacy mode as the default.",
    "Enable the copilot only after validating the selected provider and base URL.",
    "Use the solver preset list from this page as the source of truth for the UI.",
  ],
};

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
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

function asEnabledStringArray(value: unknown, fallback: string[]): string[] {
  if (Array.isArray(value)) {
    return asStringArray(value, fallback);
  }

  if (isRecord(value)) {
    const enabledKeys = Object.entries(value)
      .filter(([, enabled]) => enabled === true)
      .map(([key]) => key)
      .filter((key) => key.trim().length > 0);

    return enabledKeys.length > 0 ? enabledKeys : fallback;
  }

  return fallback;
}

function unwrapEnvelope<T>(value: unknown): T | null {
  if (!isRecord(value)) {
    return value as T | null;
  }

  if ("payload" in value && value.payload != null) {
    return value.payload as T;
  }

  if ("data" in value && value.data != null) {
    return value.data as T;
  }

  if ("result" in value && value.result != null) {
    return value.result as T;
  }

  if ("response" in value && value.response != null) {
    return value.response as T;
  }

  return value as T;
}

function getNowIso(): string {
  return new Date().toISOString();
}

function mergeConfigLabPayload(raw: unknown, defaults: ConfigLabPayload): ConfigLabPayload {
  if (!isRecord(raw)) {
    return defaults;
  }

  const samples = isRecord(raw.samples) ? raw.samples : undefined;
  const configSample = samples && isRecord(samples.config_lab) ? samples.config_lab : undefined;
  const runtime = isRecord(raw.runtime) ? raw.runtime : raw.runtimeSnapshot && isRecord(raw.runtimeSnapshot) ? raw.runtimeSnapshot : undefined;
  const runtimeLlm = runtime && isRecord(runtime.llm) ? runtime.llm : undefined;
  const llm =
    isRecord(raw.llm)
      ? raw.llm
      : isRecord(raw.llmConfig)
        ? raw.llmConfig
        : isRecord(configSample?.llm_config)
          ? configSample.llm_config
          : runtimeLlm;
  const solver =
    isRecord(raw.solver)
      ? raw.solver
      : isRecord(raw.solverConfig)
        ? raw.solverConfig
        : undefined;
  const ocr = isRecord(raw.ocr)
    ? raw.ocr
    : runtime && isRecord(runtime.ocr)
      ? runtime.ocr
      : undefined;
  const privacy = isRecord(raw.privacy) ? raw.privacy : raw.security && isRecord(raw.security) ? raw.security : undefined;
  const availablePresets = Array.isArray(raw.available_presets)
    ? raw.available_presets
    : Array.isArray(configSample?.preset_packs)
      ? configSample.preset_packs
      : [];
  const benchmarkStats = Array.isArray(raw.benchmark_stats) ? raw.benchmark_stats : [];
  const benchmarks =
    Array.isArray(raw.benchmarks)
      ? raw.benchmarks
      : Array.isArray(raw.entries)
        ? raw.entries
        : benchmarkStats.length > 0
          ? benchmarkStats
          : Array.isArray(configSample?.benchmarks)
            ? configSample.benchmarks
            : defaults.benchmarks;
  const selectedPresetId = asString(
    raw.active_preset ??
      solver?.selectedPresetId ??
      solver?.selected_preset_id,
    defaults.solver.selectedPresetId
  );
  const availablePresetIds =
    availablePresets.length > 0
      ? availablePresets
          .map((entry) =>
            isRecord(entry)
              ? asString(entry.preset_id ?? entry.id, "")
              : ""
          )
          .filter(Boolean)
      : asStringArray(
          solver?.availablePresetIds ?? solver?.available_preset_ids,
          defaults.solver.availablePresetIds
        );
  const privacyMode = (asString(
    llm?.privacyMode ??
      llm?.privacy_mode ??
      raw.privacy_mode ??
      configSample?.privacy_mode,
    defaults.llm.privacyMode
  ) as ConfigLabPrivacyMode) ?? defaults.llm.privacyMode;
  const rolesEnabled = asEnabledStringArray(llm?.rolesEnabled ?? llm?.roles_enabled, defaults.llm.rolesEnabled);
  const contextScopesEnabled = asEnabledStringArray(
    llm?.contextScopesEnabled ?? llm?.context_scopes_enabled,
    defaults.llm.contextScopesEnabled
  );
  const warnings = Array.isArray(raw.warnings)
    ? asStringArray(raw.warnings, [])
    : defaults.warnings;
  const recommendations = Array.isArray(raw.recommendations)
    ? asStringArray(raw.recommendations, [])
    : Array.isArray(raw.notes)
      ? asStringArray(raw.notes, [])
      : defaults.recommendations;

  return {
    kind: "config_lab",
    status: (asString(raw.status, defaults.status) as ConfigLabStatus) ?? defaults.status,
    source: (asString(raw.source, defaults.source) as ConfigLabSource) ?? defaults.source,
    refreshedAt: asString(raw.refreshedAt, defaults.refreshedAt),
    runtime: {
      connected: asBoolean(runtime?.connected, defaults.runtime.connected),
      transport: asString(runtime?.transport, defaults.runtime.transport),
      endpoint: asString(runtime?.endpoint, defaults.runtime.endpoint),
      refreshedAt: asString(runtime?.refreshedAt, defaults.runtime.refreshedAt),
      raw: isRecord(runtime) ? runtime : defaults.runtime.raw,
    },
    llm: {
      enabled: asBoolean(llm?.enabled, defaults.llm.enabled),
      providerMode: (asString(llm?.providerMode ?? llm?.provider_mode, defaults.llm.providerMode) as ConfigLabProviderMode) ?? defaults.llm.providerMode,
      baseUrl: asString(llm?.baseUrl ?? llm?.base_url, defaults.llm.baseUrl),
      apiKeyRef: asString(llm?.apiKeyRef ?? llm?.api_key_ref, defaults.llm.apiKeyRef),
      model: asString(llm?.model, defaults.llm.model),
      temperature: asNumber(llm?.temperature, defaults.llm.temperature),
      maxOutputTokens: asNumber(llm?.maxOutputTokens ?? llm?.max_output_tokens, defaults.llm.maxOutputTokens),
      streaming: asBoolean(llm?.streaming, defaults.llm.streaming),
      rolesEnabled,
      contextScopesEnabled,
      privacyMode,
    },
    solver: {
      selectedPresetId,
      availablePresetIds,
      treeCompression: asString(
        solver?.treeCompression ??
          solver?.tree_compression ??
          (availablePresets[0] && isRecord(availablePresets[0]) ? availablePresets[0].memory_mode : undefined),
        defaults.solver.treeCompression
      ),
      timeBudgetMs: asNumber(solver?.timeBudgetMs ?? solver?.time_budget_ms, defaults.solver.timeBudgetMs),
      cacheEnabled: asBoolean(solver?.cacheEnabled ?? solver?.cache_enabled, defaults.solver.cacheEnabled),
    },
    ocr: {
      enabledEngines: asStringArray(ocr?.enabledEngines ?? ocr?.enabled_engines, defaults.ocr.enabledEngines),
      mode: (asString(ocr?.mode, defaults.ocr.mode) as ConfigLabOcrMode) ?? defaults.ocr.mode,
      parallel: asBoolean(ocr?.parallel, defaults.ocr.parallel),
      useGpu: asBoolean(ocr?.useGpu ?? ocr?.use_gpu, defaults.ocr.useGpu),
    },
    privacy: {
      strictLocal: asBoolean(privacy?.strictLocal ?? privacy?.strict_local, privacyMode === "strict_local"),
      redactedRemote: asBoolean(privacy?.redactedRemote ?? privacy?.redacted_remote, privacyMode === "redacted_remote"),
      fullRemote: asBoolean(privacy?.fullRemote ?? privacy?.full_remote, privacyMode === "full_remote"),
    },
    benchmarks: Array.isArray(benchmarks)
      ? benchmarks
          .map((item, index) => {
            if (!isRecord(item)) {
              return null;
            }
            return {
              id: asString(item.id, `bench-${index + 1}`),
              name: asString(item.name ?? item.label, `Benchmark ${index + 1}`),
              status: (asString(item.status, benchmarkStats.length > 0 ? "ready" : "disabled") as ConfigLabBenchmarkEntry["status"]) ?? "disabled",
              score: asNumber(item.score ?? item.rating ?? item.value, 0),
              note: asString(
                item.note ??
                  item.description ??
                  (item.unit ? `${item.value}${item.unit ? ` ${item.unit}` : ""}` : ""),
                ""
              ),
            } satisfies ConfigLabBenchmarkEntry;
          })
          .filter((value): value is ConfigLabBenchmarkEntry => value !== null)
      : defaults.benchmarks,
    warnings,
    recommendations,
    raw,
  };
}

async function resolveTauriInvoke(): Promise<((command: string, args?: Record<string, unknown>) => Promise<unknown>) | null> {
  const globalWindow = globalThis as typeof globalThis & {
    __TAURI__?: {
      core?: { invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown> };
      invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
    };
  };

  if (typeof globalWindow.__TAURI__?.core?.invoke === "function") {
    return globalWindow.__TAURI__!.core!.invoke!;
  }

  if (typeof globalWindow.__TAURI__?.invoke === "function") {
    return globalWindow.__TAURI__!.invoke!;
  }

  try {
    const core = await import("@tauri-apps/api/core");
    if (typeof core.invoke === "function") {
      return core.invoke;
    }
  } catch {
    // Ignore: browser-only or package not installed.
  }

  return null;
}

async function tryInvokePayload<T>(commands: string[], args?: Record<string, unknown>): Promise<T | null> {
  const invoke = await resolveTauriInvoke();
  if (!invoke) {
    return null;
  }

  for (const command of commands) {
    try {
      return unwrapEnvelope<T>(await invoke(command, args));
    } catch {
      // Try the next command name.
    }
  }

  return null;
}

async function tryFetchPayload<T>(urls: string[]): Promise<T | null> {
  for (const url of urls) {
    try {
      const controller = new AbortController();
      const timeout = globalThis.setTimeout(() => controller.abort(), 2500);
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
      globalThis.clearTimeout(timeout);
      if (!response.ok) {
        continue;
      }
      return unwrapEnvelope<T>(await response.json());
    } catch {
      // Try the next URL.
    }
  }

  return null;
}

function createRuntimeSnapshot(source: ConfigLabSource, transport: string, endpoint: string, raw?: Record<string, unknown>): ConfigLabRuntimeSnapshot {
  return {
    connected: source !== "offline" && source !== "error",
    transport,
    endpoint,
    refreshedAt: getNowIso(),
    raw,
  };
}

export function createDefaultConfigLabPayload(): ConfigLabPayload {
  return {
    ...DEFAULT_CONFIG_LAB_PAYLOAD,
    refreshedAt: getNowIso(),
    runtime: {
      ...DEFAULT_CONFIG_LAB_PAYLOAD.runtime,
      refreshedAt: getNowIso(),
    },
  };
}

async function loadConfigLabPayloadInternal(mode: ConfigLabRefreshMode): Promise<ConfigLabPayload> {
  const tauriCommands =
    mode === "refresh"
      ? ["config_lab_refresh_stub", "config_lab_default_payload"]
      : ["config_lab_default_payload", "config_lab_refresh_stub"];
  const restUrls =
    mode === "refresh"
      ? [
          "/config-lab/refresh",
          "http://127.0.0.1:8005/config-lab/refresh",
          "/config-lab/payload",
          "http://127.0.0.1:8005/config-lab/payload",
          "/runtime-snapshot",
          "http://127.0.0.1:8005/runtime-snapshot",
        ]
      : [
          "/config-lab/payload",
          "http://127.0.0.1:8005/config-lab/payload",
          "/runtime-snapshot",
          "http://127.0.0.1:8005/runtime-snapshot",
        ];

  const tauriPayload = await tryInvokePayload<unknown>(tauriCommands);
  if (tauriPayload) {
    const defaults = createDefaultConfigLabPayload();
    return mergeConfigLabPayload(tauriPayload, {
      ...defaults,
      status: "ready",
      source: "tauri",
      runtime: createRuntimeSnapshot("tauri", "tauri", tauriCommands[0]),
      warnings: defaults.warnings,
    });
  }

  const restPayload = await tryFetchPayload<unknown>(restUrls);
  if (restPayload) {
    const defaults = createDefaultConfigLabPayload();
    return mergeConfigLabPayload(restPayload, {
      ...defaults,
      status: "degraded",
      source: "runtime",
      runtime: createRuntimeSnapshot("runtime", "rest", restUrls[0]),
      warnings: [
        "Loaded config lab payload from a local runtime snapshot.",
        ...defaults.warnings,
      ],
    });
  }

  return createDefaultConfigLabPayload();
}

export async function loadConfigLabPayload(): Promise<ConfigLabPayload> {
  return loadConfigLabPayloadInternal("load");
}

export async function refreshConfigLabPayload(): Promise<ConfigLabPayload> {
  return loadConfigLabPayloadInternal("refresh");
}
