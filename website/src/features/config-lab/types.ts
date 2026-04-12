import type { LlmPrivacyMode, LlmProviderMode, LlmRoleMap, LlmScopeMap } from "../llm/types";
import type { RuntimeSnapshot } from "../../lib/runtime";

export type ConfigLabPresetPackFamily =
  | "baseline"
  | "pressure"
  | "endgame"
  | "benchmark"
  | "custom";

export type ConfigLabBackendKind =
  | "native_rust"
  | "tauri_host"
  | "http_server"
  | "browser_fallback";

export type ConfigLabBackendState = "ready" | "degraded" | "offline" | "unknown";

export type ConfigLabBenchmarkSuiteId =
  | "native_solve"
  | "http_parity"
  | "pokerkit_validation"
  | "rlcard_offline"
  | "llm_assist_smoke";

export type ConfigLabBenchmarkSuiteState =
  | "ready"
  | "queued"
  | "blocked"
  | "disabled"
  | "unknown";

export type ConfigLabReadinessState = "ready" | "partial" | "blocked" | "offline";

export interface ConfigLabPresetPack {
  id: string;
  label: string;
  family: ConfigLabPresetPackFamily;
  description: string;
  treePresetIds: string[];
  benchmarkSuites: ConfigLabBenchmarkSuiteId[];
  recommended: boolean;
  tags: string[];
}

export interface ConfigLabBackendAvailability {
  id: string;
  kind: ConfigLabBackendKind;
  label: string;
  state: ConfigLabBackendState;
  healthy: boolean;
  source: RuntimeSnapshot["source"] | "unknown";
  reason: string;
  latencyMs: number | null;
  supportsSolve: boolean;
  supportsBenchmarks: boolean;
  supportsCopilot: boolean;
  preferred: boolean;
}

export interface ConfigLabBenchmarkSuite {
  id: ConfigLabBenchmarkSuiteId;
  label: string;
  description: string;
  state: ConfigLabBenchmarkSuiteState;
  ready: boolean;
  coverage: number;
  requiredTools: string[];
  notes: string[];
}

export interface ConfigLabBenchmarkReadiness {
  state: ConfigLabReadinessState;
  ready: boolean;
  coverageScore: number;
  lastRunAt: string | null;
  notes: string[];
  blockedBy: string[];
  recommendedActions: string[];
}

export interface ConfigLabLlmSummary {
  enabled: boolean;
  providerMode: LlmProviderMode;
  providerLabel: string;
  privacyMode: LlmPrivacyMode;
  privacyLabel: string;
  baseUrl: string;
  apiKeyRef: string;
  model: string;
  temperature: number;
  maxOutputTokens: number;
  streaming: boolean;
  rolesEnabled: LlmRoleMap;
  contextScopesEnabled: LlmScopeMap;
  activeRoles: string[];
  activeScopes: string[];
  roleCount: number;
  scopeCount: number;
  networkRequired: boolean;
  posture: "disabled" | "ready" | "degraded";
}

export interface ConfigLabSummaryMetric {
  label: string;
  value: string;
  detail: string;
  tone: "positive" | "neutral" | "warning" | "critical";
}

export interface ConfigLabPayload {
  id: string;
  generatedAt: string;
  runtimeSource: RuntimeSnapshot["source"] | "unknown";
  appName: string;
  version: string;
  runtime: string;
  status: string;
  healthy: boolean;
  devMode: boolean;
  uptimeMs: number;
  selectedPresetPackId: string;
  presetPacks: ConfigLabPresetPack[];
  activePresetPack: ConfigLabPresetPack;
  backends: ConfigLabBackendAvailability[];
  llm: ConfigLabLlmSummary;
  benchmarkSuites: ConfigLabBenchmarkSuite[];
  benchmarkReadiness: ConfigLabBenchmarkReadiness;
  summary: ConfigLabSummaryMetric[];
  warnings: string[];
}
