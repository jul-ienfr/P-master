import {
  LlmConfig,
  LlmPrivacyMode,
  LlmProviderMode,
  LlmRole,
  LlmRoleMap,
  LlmScope,
  LlmScopeMap,
  LlmAssistTask,
  LlmAssistTaskKind,
} from "./types";

export const DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1";
export const DEFAULT_LLM_MODEL = "gpt-4.1-mini";

const DEFAULT_ROLE_MAP: LlmRoleMap = {
  analysis: false,
  operator_assistance: false,
  strategy_coach: false,
  replay_review: false,
};

const DEFAULT_SCOPE_MAP: LlmScopeMap = {
  spot: false,
  decision: false,
  replay: false,
  runtime: false,
  ocr: false,
  settings: false,
  fallback: false,
};

export function createDefaultLlmConfig(overrides: Partial<LlmConfig> = {}): LlmConfig {
  return {
    enabled: false,
    providerMode: "disabled",
    baseUrl: DEFAULT_LLM_BASE_URL,
    apiKeyRef: "",
    model: DEFAULT_LLM_MODEL,
    temperature: 0.2,
    maxOutputTokens: 512,
    streaming: false,
    rolesEnabled: { ...DEFAULT_ROLE_MAP, ...(overrides.rolesEnabled ?? {}) },
    contextScopesEnabled: {
      ...DEFAULT_SCOPE_MAP,
      ...(overrides.contextScopesEnabled ?? {}),
    },
    privacyMode: "strict_local",
    ...overrides,
  };
}

export function normalizeLlmConfig(config: Partial<LlmConfig> | undefined): LlmConfig {
  return createDefaultLlmConfig(config ?? {});
}

export function isLlmOptionallyEnabled(config: LlmConfig): boolean {
  return config.enabled && config.providerMode !== "disabled";
}

export function getLlmTaskRole(kind: LlmAssistTaskKind): LlmRole {
  switch (kind) {
    case "ocr_diagnostic":
    case "fallback_diagnostic":
      return "operator_assistance";
    case "session_summary":
    case "replay_coach":
      return "replay_review";
    case "strategy_review":
      return "strategy_coach";
    case "spot_explain":
    case "line_compare":
    case "decision_rationale":
    default:
      return "analysis";
  }
}

export function getLlmTaskScopes(kind: LlmAssistTaskKind): LlmScope[] {
  switch (kind) {
    case "ocr_diagnostic":
      return ["ocr", "runtime"];
    case "fallback_diagnostic":
      return ["fallback", "runtime"];
    case "session_summary":
    case "replay_coach":
      return ["replay", "runtime"];
    case "strategy_review":
      return ["settings", "replay"];
    case "line_compare":
    case "decision_rationale":
      return ["spot", "decision"];
    case "spot_explain":
    default:
      return ["spot"];
  }
}

export function isLlmTaskAllowed(config: LlmConfig, task: LlmAssistTask): boolean {
  if (!config.enabled || config.providerMode === "disabled") {
    return false;
  }

  const role = getLlmTaskRole(task.kind);
  if (!config.rolesEnabled[role]) {
    return false;
  }

  const scopes = task.focusScopes && task.focusScopes.length > 0 ? task.focusScopes : getLlmTaskScopes(task.kind);
  return scopes.every((scope) => config.contextScopesEnabled[scope]);
}

export function getLlmProviderLabel(mode: LlmProviderMode): string {
  switch (mode) {
    case "openai_compatible_local":
      return "Compatible OpenAI local";
    case "openai_compatible_remote":
      return "Compatible OpenAI distant";
    case "disabled":
    default:
      return "Désactivé";
  }
}

export function getLlmPrivacyLabel(mode: LlmPrivacyMode): string {
  switch (mode) {
    case "strict_local":
      return "Local strict";
    case "redacted_remote":
      return "Distant anonymisé";
    case "full_remote":
      return "Distant complet";
    default:
      return "Local strict";
  }
}
