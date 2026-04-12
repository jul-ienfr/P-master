import { createDefaultLlmConfig } from "../features/llm/config";
import type { LlmAssistResponse, LlmAssistTask, LlmConfig } from "../features/llm/types";

const LOCAL_RUNTIME_URLS = ["http://127.0.0.1:8080", "http://127.0.0.1:8005"];
const LOCAL_GTO_URL = "http://127.0.0.1:8765";
const LLM_CONFIG_STORAGE_KEY = "pokermaster:v2:llm-config";
export const LLM_CONFIG_UPDATED_EVENT = "pokermaster:llm-config-updated";

type UnknownRecord = Record<string, unknown>;

type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

export interface RuntimeSnapshot {
  source: "tauri" | "local_rest" | "fallback";
  appName: string;
  version: string;
  runtime: string;
  devMode: boolean;
  httpFallbackEnabled: boolean;
  llm: LlmConfig;
  healthy: boolean;
  status: string;
  uptimeMs: number;
}

function asRecord(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : {};
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizeRolesEnabled(raw: UnknownRecord): LlmConfig["rolesEnabled"] {
  const roleHints = new Set(asStringArray(raw.roles_enabled));
  return {
    analysis:
      roleHints.has("analysis") ||
      roleHints.has("spot_explain") ||
      roleHints.has("line_compare") ||
      roleHints.has("decision_rationale"),
    operator_assistance:
      roleHints.has("operator_assistance") ||
      roleHints.has("ocr_diagnostic") ||
      roleHints.has("fallback_diagnostic"),
    strategy_coach:
      roleHints.has("strategy_coach") || roleHints.has("strategy_review"),
    replay_review:
      roleHints.has("replay_review") ||
      roleHints.has("session_summary") ||
      roleHints.has("replay_coach"),
  };
}

function normalizeScopesEnabled(raw: UnknownRecord): LlmConfig["contextScopesEnabled"] {
  const scopeHints = new Set(asStringArray(raw.context_scopes_enabled));
  return {
    spot: scopeHints.has("spot") || scopeHints.has("spot_snapshot"),
    decision: scopeHints.has("decision") || scopeHints.has("decision_snapshot"),
    replay: scopeHints.has("replay"),
    runtime: scopeHints.has("runtime") || scopeHints.has("runtime_metrics"),
    ocr: scopeHints.has("ocr"),
    settings: scopeHints.has("settings") || scopeHints.has("config"),
    fallback: scopeHints.has("fallback"),
  };
}

function normalizeLlmConfig(rawValue: unknown): LlmConfig {
  const raw = asRecord(rawValue);
  return createDefaultLlmConfig({
    enabled: asBoolean(raw.enabled),
    providerMode:
      asString(raw.provider_mode, "disabled") as LlmConfig["providerMode"],
    baseUrl: asString(raw.base_url),
    apiKeyRef: asString(raw.api_key_ref),
    model: asString(raw.model),
    temperature: asNumber(raw.temperature, 0.2),
    maxOutputTokens: asNumber(raw.max_output_tokens, 512),
    streaming: asBoolean(raw.streaming),
    privacyMode:
      asString(raw.privacy_mode, "strict_local") as LlmConfig["privacyMode"],
    rolesEnabled: normalizeRolesEnabled(raw),
    contextScopesEnabled: normalizeScopesEnabled(raw),
  });
}

function toTauriLlmConfig(config: LlmConfig): UnknownRecord {
  const rolesEnabled: string[] = [];
  if (config.rolesEnabled.analysis) {
    rolesEnabled.push("spot_explain", "line_compare", "decision_rationale");
  }
  if (config.rolesEnabled.operator_assistance) {
    rolesEnabled.push("ocr_diagnostic", "fallback_diagnostic");
  }
  if (config.rolesEnabled.strategy_coach) {
    rolesEnabled.push("strategy_review");
  }
  if (config.rolesEnabled.replay_review) {
    rolesEnabled.push("session_summary", "replay_coach");
  }

  const contextScopesEnabled: string[] = [];
  if (config.contextScopesEnabled.spot) {
    contextScopesEnabled.push("spot_snapshot");
  }
  if (config.contextScopesEnabled.decision) {
    contextScopesEnabled.push("decision_snapshot");
  }
  if (config.contextScopesEnabled.replay) {
    contextScopesEnabled.push("replay");
  }
  if (config.contextScopesEnabled.runtime) {
    contextScopesEnabled.push("runtime_metrics");
  }
  if (config.contextScopesEnabled.ocr) {
    contextScopesEnabled.push("ocr");
  }
  if (config.contextScopesEnabled.settings) {
    contextScopesEnabled.push("config");
  }
  if (config.contextScopesEnabled.fallback) {
    contextScopesEnabled.push("fallback");
  }

  return {
    enabled: config.enabled,
    provider_mode: config.providerMode,
    base_url: config.baseUrl || null,
    api_key_ref: config.apiKeyRef || null,
    model: config.model || null,
    temperature: config.temperature,
    max_output_tokens: config.maxOutputTokens,
    streaming: config.streaming,
    roles_enabled: rolesEnabled,
    context_scopes_enabled: contextScopesEnabled,
    privacy_mode: config.privacyMode,
  };
}

function normalizeRuntimeSnapshot(rawValue: unknown, source: RuntimeSnapshot["source"]): RuntimeSnapshot {
  const envelope = asRecord(rawValue);
  const nestedRuntime = asRecord(envelope.runtime);
  const raw = Object.keys(nestedRuntime).length > 0 ? nestedRuntime : envelope;
  const llm = normalizeLlmConfig(raw.llm ?? asRecord(raw.samples).llm_config);
  const status = asString(raw.status, "ok");
  return {
    source,
    appName: asString(raw.app_name, asString(raw.service, "PokerMaster")),
    version: asString(raw.version, asString(raw.api_version, "v2")),
    runtime: asString(raw.runtime, source === "tauri" ? "tauri" : "local_rest"),
    devMode: asBoolean(raw.dev_mode),
    httpFallbackEnabled: asBoolean(raw.http_fallback_enabled, true),
    llm,
    healthy: asBoolean(raw.healthy, status === "ok"),
    status,
    uptimeMs: asNumber(raw.uptime_ms),
  };
}

function summarizeTask(task: LlmAssistTask): string | undefined {
  const fragments = [task.title, task.instruction].filter(
    (value): value is string => typeof value === "string" && value.trim().length > 0
  );
  return fragments.length > 0 ? fragments.join(" | ") : undefined;
}

function buildTaskTags(task: LlmAssistTask): string[] {
  const scopes = task.focusScopes ?? [];
  const surface = task.ui?.surface ? [task.ui.surface] : [];
  return [task.kind, ...surface, ...scopes].filter((value, index, array) => array.indexOf(value) === index);
}

function normalizeAssistResponse(rawValue: unknown): LlmAssistResponse {
  const raw = asRecord(rawValue);
  return {
    summary: asString(raw.summary, "Local copilot stub completed."),
    recommendations: asStringArray(raw.recommendations),
    warnings: asStringArray(raw.warnings),
    confidence: asNumber(raw.confidence, 0.15),
    usedContext: asStringArray(raw.used_context ?? raw.usedContext),
    latencyMs: asNumber(raw.latency_ms ?? raw.latencyMs),
    providerMetadata: asRecord(raw.provider_metadata ?? raw.providerMetadata),
    rawText: asString(raw.raw_text ?? raw.rawText),
  };
}

function loadStoredLlmConfig(): LlmConfig | null {
  if (typeof localStorage === "undefined") {
    return null;
  }
  try {
    const rawValue = localStorage.getItem(LLM_CONFIG_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }
    return normalizeLlmConfig(JSON.parse(rawValue));
  } catch {
    return null;
  }
}

function persistStoredLlmConfig(config: LlmConfig): void {
  if (typeof localStorage === "undefined") {
    return;
  }
  try {
    localStorage.setItem(LLM_CONFIG_STORAGE_KEY, JSON.stringify(toTauriLlmConfig(config)));
  } catch {
    // Ignore storage failures and keep the config in memory only.
  }
}

function emitLlmConfigUpdated(config: LlmConfig): void {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") {
    return;
  }
  try {
    window.dispatchEvent(new CustomEvent(LLM_CONFIG_UPDATED_EVENT, { detail: config }));
  } catch {
    // Ignore event dispatch failures.
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

function applyStoredLlmConfig(snapshot: RuntimeSnapshot): RuntimeSnapshot {
  const stored = loadStoredLlmConfig();
  if (!stored) {
    return snapshot;
  }
  return {
    ...snapshot,
    llm: stored,
  };
}

async function fetchJson(url: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function fetchJsonFromCandidates(paths: string[]): Promise<unknown> {
  for (const url of paths) {
    try {
      return await fetchJson(url);
    } catch {
      // Try the next runtime candidate.
    }
  }
  throw new Error("Runtime endpoints unavailable");
}

export async function loadRuntimeSnapshot(): Promise<RuntimeSnapshot> {
  try {
    const snapshot = await fetchJsonFromCandidates(
      LOCAL_RUNTIME_URLS.map((url) => `${url}/runtime-snapshot`)
    );
    return applyStoredLlmConfig(normalizeRuntimeSnapshot(snapshot, "local_rest"));
  } catch {
    // Fall back to the shell runtime when no live Python runtime is reachable.
  }

  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const runtimeConfig = await invoke("runtime_config");
      const health = await invoke("health").catch(() => ({}));
      return applyStoredLlmConfig(
        normalizeRuntimeSnapshot({ ...asRecord(runtimeConfig), ...asRecord(health) }, "tauri")
      );
    }
  } catch {
    return applyStoredLlmConfig(
      normalizeRuntimeSnapshot(
        {
          status: "offline",
          service: "PokerMaster",
          version: "v2",
          runtime: "browser",
          http_fallback_enabled: true,
          llm: { enabled: false, provider_mode: "disabled" },
        },
        "fallback"
      )
    );
  }

  return applyStoredLlmConfig(
    normalizeRuntimeSnapshot(
      {
        status: "offline",
        service: "PokerMaster",
        version: "v2",
        runtime: "browser",
        http_fallback_enabled: true,
        llm: { enabled: false, provider_mode: "disabled" },
      },
      "fallback"
    )
  );
}

export async function persistLlmConfig(config: LlmConfig): Promise<LlmConfig> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("set_llm_config", {
        config: toTauriLlmConfig(config),
      });
      const normalized = normalizeLlmConfig(response);
      persistStoredLlmConfig(normalized);
      emitLlmConfigUpdated(normalized);
      return normalized;
    }
  } catch {
    // Persist to browser storage below.
  }

  persistStoredLlmConfig(config);
  emitLlmConfigUpdated(config);
  return config;
}

export async function runLocalLlmAssist(
  task: LlmAssistTask,
  config: LlmConfig
): Promise<LlmAssistResponse> {
  try {
    const invoke = await resolveTauriInvoke();
    if (invoke) {
      const response = await invoke("llm_mock_assist", {
        request: {
          task: task.kind,
          context_summary: summarizeTask(task) ?? null,
          notes: task.instruction ?? null,
          tags: buildTaskTags(task),
          spot: task.spot ?? null,
          decision: task.decision ?? null,
          replay: task.replay ?? null,
          ui: task.ui ?? null,
        },
      });
      return normalizeAssistResponse(response);
    }
  } catch {
    // Fall back to HTTP endpoints below.
  }

  try {
    const urls = [
      `${LOCAL_GTO_URL}/v2/llm/assist`,
      ...LOCAL_RUNTIME_URLS.map((url) => `${url}/v2/llm/assist`),
    ];
    for (const url of urls) {
      try {
        const response = await fetchJson(url, {
          method: "POST",
          headers: {
            "content-type": "application/json",
          },
          body: JSON.stringify({
            task: task.kind,
            prompt: task.instruction ?? task.title ?? null,
            provider_mode: config.providerMode,
            model: config.model,
            base_url: config.baseUrl,
            enabled: config.enabled,
            temperature: config.temperature,
            max_output_tokens: config.maxOutputTokens,
            streaming: config.streaming,
            tags: buildTaskTags(task),
            context_summary: summarizeTask(task) ?? null,
            notes: task.instruction ?? task.title ?? null,
            spot: task.spot ?? null,
            decision: task.decision ?? null,
            replay: task.replay ?? null,
            ui: task.ui ?? null,
            context: {
              surface: task.ui?.surface ?? "",
              scopes: buildTaskTags(task).join(","),
            },
          }),
        });
        return normalizeAssistResponse(response);
      } catch {
        // Try the next local assist endpoint.
      }
    }
    throw new Error("local copilot unavailable");
  } catch (error) {
    const reason = error instanceof Error ? error.message : "local copilot unavailable";
    return {
      summary: `Local copilot fallback: ${reason}`,
      recommendations: [
        "Continue with the deterministic solver and equity engines.",
        "Re-enable the provider later if you want explanatory assistance.",
      ],
      warnings: [reason],
      confidence: 0,
      usedContext: buildTaskTags(task),
      latencyMs: 0,
      providerMetadata: {
        source: "browser_fallback",
        providerMode: config.providerMode,
      },
    };
  }
}
