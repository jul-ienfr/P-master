import { getLlmPrivacyLabel, getLlmProviderLabel } from "../llm/config";
import type { RuntimeSnapshot } from "../../lib/runtime";
import { createDefaultConfigLabPayload as createDefaultConfigLabPayloadFixture } from "./fixtures";
import {
  getConfigLabPresetPack,
  getDefaultConfigLabPresetPackId,
  listConfigLabPresetPacks,
} from "./presets";
import type {
  ConfigLabBackendAvailability,
  ConfigLabBackendState,
  ConfigLabBenchmarkReadiness,
  ConfigLabBenchmarkSuite,
  ConfigLabBenchmarkSuiteId,
  ConfigLabBenchmarkSuiteState,
  ConfigLabLlmSummary,
  ConfigLabPayload,
  ConfigLabSummaryMetric,
} from "./types";

function cloneMetrics(metrics: ConfigLabSummaryMetric[]): ConfigLabSummaryMetric[] {
  return metrics.map((metric) => ({ ...metric }));
}

function countEnabledFlags(flags: Record<string, boolean>): number {
  return Object.values(flags).filter(Boolean).length;
}

function buildLlmSummary(runtime: RuntimeSnapshot): ConfigLabLlmSummary {
  const llm = runtime.llm;
  const activeRoles: string[] = [];
  const activeScopes: string[] = [];

  for (const [role, enabled] of Object.entries(llm.rolesEnabled)) {
    if (enabled) {
      activeRoles.push(role);
    }
  }

  for (const [scope, enabled] of Object.entries(llm.contextScopesEnabled)) {
    if (enabled) {
      activeScopes.push(scope);
    }
  }

  const networkRequired = llm.enabled && llm.providerMode === "openai_compatible_remote";
  const posture: ConfigLabLlmSummary["posture"] =
    !llm.enabled || llm.providerMode === "disabled"
      ? "disabled"
      : activeRoles.length > 0 && activeScopes.length > 0
        ? "ready"
        : "degraded";

  return {
    enabled: llm.enabled,
    providerMode: llm.providerMode,
    providerLabel: getLlmProviderLabel(llm.providerMode),
    privacyMode: llm.privacyMode,
    privacyLabel: getLlmPrivacyLabel(llm.privacyMode),
    baseUrl: llm.baseUrl,
    apiKeyRef: llm.apiKeyRef,
    model: llm.model,
    temperature: llm.temperature,
    maxOutputTokens: llm.maxOutputTokens,
    streaming: llm.streaming,
    rolesEnabled: { ...llm.rolesEnabled },
    contextScopesEnabled: { ...llm.contextScopesEnabled },
    activeRoles,
    activeScopes,
    roleCount: countEnabledFlags(llm.rolesEnabled),
    scopeCount: countEnabledFlags(llm.contextScopesEnabled),
    networkRequired,
    posture,
  };
}

function buildBackendAvailability(runtime: RuntimeSnapshot): ConfigLabBackendAvailability[] {
  const browserFallback: ConfigLabBackendAvailability = {
    id: "browser_fallback",
    kind: "browser_fallback",
    label: "Browser fallback",
    state: "ready",
    healthy: true,
    source: runtime.source,
    reason: "Deterministic offline payloads remain available even when the host is absent.",
    latencyMs: 0,
    supportsSolve: false,
    supportsBenchmarks: false,
    supportsCopilot: true,
    preferred: false,
  };

  const nativeBackendState: ConfigLabBackendState =
    runtime.source === "fallback" ? "offline" : runtime.healthy ? "ready" : "degraded";
  const tauriBackendState: ConfigLabBackendState =
    runtime.source === "tauri"
      ? "ready"
      : runtime.source === "local_rest"
        ? "degraded"
        : "offline";
  const httpBackendState: ConfigLabBackendState = runtime.httpFallbackEnabled
    ? runtime.source === "local_rest"
      ? "ready"
      : "degraded"
    : "offline";

  return [
    {
      id: "native_rust",
      kind: "native_rust",
      label: "Native Rust engine",
      state: nativeBackendState,
      healthy: nativeBackendState === "ready",
      source: runtime.source,
      reason:
        nativeBackendState === "offline"
          ? "No host-backed runtime snapshot is active."
          : "Primary solver and equity engine are available locally.",
      latencyMs: null,
      supportsSolve: true,
      supportsBenchmarks: true,
      supportsCopilot: false,
      preferred: runtime.source !== "fallback",
    },
    {
      id: "tauri_host",
      kind: "tauri_host",
      label: "Tauri host",
      state: tauriBackendState,
      healthy: tauriBackendState === "ready",
      source: runtime.source,
      reason:
        tauriBackendState === "ready"
          ? "Desktop host commands are available."
          : "Desktop host commands are not the active source.",
      latencyMs: null,
      supportsSolve: true,
      supportsBenchmarks: true,
      supportsCopilot: true,
      preferred: runtime.source === "tauri",
    },
    {
      id: "http_server",
      kind: "http_server",
      label: "Local HTTP server",
      state: httpBackendState,
      healthy: httpBackendState === "ready",
      source: runtime.source,
      reason: runtime.httpFallbackEnabled
        ? "HTTP fallback is enabled for local isolation and debugging."
        : "HTTP fallback is disabled in the current runtime snapshot.",
      latencyMs: null,
      supportsSolve: true,
      supportsBenchmarks: true,
      supportsCopilot: true,
      preferred: runtime.source === "local_rest",
    },
    browserFallback,
  ];
}

function buildBenchmarkSuites(
  runtime: RuntimeSnapshot,
  backends: ConfigLabBackendAvailability[]
): ConfigLabBenchmarkSuite[] {
  const backendById = new Map(backends.map((backend) => [backend.id, backend]));
  const nativeBackend = backendById.get("native_rust");
  const httpBackend = backendById.get("http_server");

  const suiteState = {
    native_solve: nativeBackend?.healthy ? "ready" : nativeBackend?.state === "offline" ? "blocked" : "queued",
    http_parity: httpBackend?.healthy ? "ready" : httpBackend?.state === "offline" ? "blocked" : "queued",
    pokerkit_validation: "queued",
    rlcard_offline: "queued",
    llm_assist_smoke:
      runtime.llm.enabled && runtime.llm.providerMode !== "disabled" ? "queued" : "disabled",
  } as Record<ConfigLabBenchmarkSuiteId, ConfigLabBenchmarkSuiteState>;

  const suites: ConfigLabBenchmarkSuite[] = [
    {
      id: "native_solve",
      label: "Native solve parity",
      description: "Validate the local Rust solve path against known fixtures and cached spots.",
      state: suiteState.native_solve,
      ready: suiteState.native_solve === "ready",
      coverage: suiteState.native_solve === "ready" ? 100 : suiteState.native_solve === "queued" ? 45 : 0,
      requiredTools: ["native rust engine", "solver-studio fixtures"],
      notes: [
        "Primary V2 solve path should remain the first benchmark gate.",
      ],
    },
    {
      id: "http_parity",
      label: "HTTP parity",
      description: "Confirm the local HTTP fallback returns the same normalized decision shape.",
      state: suiteState.http_parity,
      ready: suiteState.http_parity === "ready",
      coverage: suiteState.http_parity === "ready" ? 100 : suiteState.http_parity === "queued" ? 35 : 0,
      requiredTools: ["local REST runtime", "normalization bridge"],
      notes: ["Useful for isolation, debugging, and host fallback verification."],
    },
    {
      id: "pokerkit_validation",
      label: "PokerKit validation",
      description: "Replay and rules-check harness for legal actions, streets, and side-pot safety.",
      state: suiteState.pokerkit_validation,
      ready: false,
      coverage: 0,
      requiredTools: ["PokerKit oracle", "replay fixtures"],
      notes: ["Queued until the validation harness is wired into the app."],
    },
    {
      id: "rlcard_offline",
      label: "RLCard offline",
      description: "Offline self-play and policy comparison loop for long-running study jobs.",
      state: suiteState.rlcard_offline,
      ready: false,
      coverage: 0,
      requiredTools: ["RLCard", "seeded offline jobs"],
      notes: ["Useful for regression tracking and learning experiments."],
    },
    {
      id: "llm_assist_smoke",
      label: "LLM assist smoke",
      description: "Optional OpenAI-format copilot smoke test for explanations and operator help.",
      state: suiteState.llm_assist_smoke,
      ready: suiteState.llm_assist_smoke === "ready",
      coverage: suiteState.llm_assist_smoke === "ready" ? 100 : 0,
      requiredTools: ["optional LLM provider", "privacy-safe context routing"],
      notes: ["Disabled until the copilot is explicitly enabled."],
    },
  ];

  return suites;
}

function buildBenchmarkReadiness(
  suites: ConfigLabBenchmarkSuite[]
): ConfigLabBenchmarkReadiness {
  const activeSuites = suites.filter((suite) => suite.state !== "disabled");
  const readySuites = activeSuites.filter((suite) => suite.ready);
  const blockedSuites = suites.filter((suite) => suite.state === "blocked");
  const queuedSuites = suites.filter((suite) => suite.state === "queued");
  const offlineSuites = suites.filter((suite) => suite.state === "unknown");

  let state: ConfigLabBenchmarkReadiness["state"] = "partial";
  if (activeSuites.length > 0 && readySuites.length === activeSuites.length) {
    state = "ready";
  } else if (readySuites.length === 0 && blockedSuites.length > 0) {
    state = "blocked";
  } else if (activeSuites.length === 0) {
    state = "offline";
  }

  const coverageScore =
    activeSuites.length > 0 ? Math.round((readySuites.length / activeSuites.length) * 100) : 0;

  const notes: string[] = [];
  if (queuedSuites.length > 0) {
    notes.push(`${queuedSuites.length} benchmark suite(s) remain queued.`);
  }
  if (offlineSuites.length > 0) {
    notes.push(`${offlineSuites.length} benchmark suite(s) are still unknown.`);
  }
  if (readySuites.length > 0) {
    notes.push(`${readySuites.length} benchmark suite(s) are already ready.`);
  }

  const blockedBy = blockedSuites.map((suite) => suite.label);
  const recommendedActions = blockedSuites.length > 0 || queuedSuites.length > 0
    ? [
        "Wire the validation harnesses into the application shell.",
        "Connect the offline benchmark runners once the runtime bridge is stable.",
      ]
    : ["Benchmark readiness is already green enough for the current slice."];

  return {
    state,
    ready: state === "ready",
    coverageScore,
    lastRunAt: null,
    notes,
    blockedBy,
    recommendedActions,
  };
}

function buildSummary(
  payload: ConfigLabPayload,
  benchmarkReadiness: ConfigLabBenchmarkReadiness,
  backends: ConfigLabBackendAvailability[]
): ConfigLabSummaryMetric[] {
  return cloneMetrics([
    {
      label: "Preset packs",
      value: `${payload.presetPacks.length} ready`,
      detail: payload.activePresetPack.label,
      tone: "positive",
    },
    {
      label: "Backends",
      value: `${backends.filter((backend) => backend.state === "ready").length} ready`,
      detail: backends.find((backend) => backend.preferred)?.label ?? "No preferred backend",
      tone: payload.healthy ? "positive" : "warning",
    },
    {
      label: "LLM",
      value: payload.llm.posture === "disabled" ? "Disabled" : payload.llm.providerLabel,
      detail: payload.llm.privacyLabel,
      tone: payload.llm.posture === "ready" ? "positive" : payload.llm.posture === "degraded" ? "warning" : "neutral",
    },
    {
      label: "Bench readiness",
      value: benchmarkReadiness.state === "ready" ? "Ready" : benchmarkReadiness.state === "partial" ? "Partial" : benchmarkReadiness.state,
      detail: `${benchmarkReadiness.coverageScore}% coverage`,
      tone: benchmarkReadiness.ready ? "positive" : benchmarkReadiness.state === "blocked" ? "critical" : "warning",
    },
  ]);
}

export function createDefaultConfigLabPayload(
  overrides: Partial<ConfigLabPayload> = {}
): ConfigLabPayload {
  return createDefaultConfigLabPayloadFixture(overrides);
}

export function mapRuntimeSnapshotToConfigLabPayload(
  runtime: RuntimeSnapshot,
  selectedPresetPackId: string = getDefaultConfigLabPresetPackId()
): ConfigLabPayload {
  const presetPacks = listConfigLabPresetPacks();
  const activePresetPack = getConfigLabPresetPack(selectedPresetPackId);
  const llm = buildLlmSummary(runtime);
  const backends = buildBackendAvailability(runtime);
  const benchmarkSuites = buildBenchmarkSuites(runtime, backends);
  const benchmarkReadiness = buildBenchmarkReadiness(benchmarkSuites);

  const payload: ConfigLabPayload = {
    id: `config-lab-${runtime.source}-${runtime.runtime}`,
    generatedAt: new Date().toISOString(),
    runtimeSource: runtime.source,
    appName: runtime.appName,
    version: runtime.version,
    runtime: runtime.runtime,
    status: runtime.status,
    healthy: runtime.healthy,
    devMode: runtime.devMode,
    uptimeMs: runtime.uptimeMs,
    selectedPresetPackId: activePresetPack.id,
    presetPacks,
    activePresetPack,
    backends,
    llm,
    benchmarkSuites,
    benchmarkReadiness,
    summary: [],
    warnings: runtime.healthy ? [] : ["runtime snapshot indicates a degraded or offline host"],
  };

  payload.summary = buildSummary(payload, benchmarkReadiness, backends);
  return payload;
}
