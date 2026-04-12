import { createDefaultLlmConfig, getLlmProviderLabel } from "./config";
import { LlmAssistResponse, LlmAssistTask, LlmProviderStatus, LlmConfig } from "./types";

export function createDefaultLlmProviderStatus(config?: Partial<LlmConfig>): LlmProviderStatus {
  const normalized = createDefaultLlmConfig(config ?? {});

  if (!normalized.enabled || normalized.providerMode === "disabled") {
    return {
      state: "disabled",
      healthy: false,
      reason: "LLM is disabled by default",
      providerMode: normalized.providerMode,
      baseUrl: normalized.baseUrl,
      model: normalized.model,
      apiKeyRef: normalized.apiKeyRef,
      latencyMs: null,
      lastCheckedAt: null,
    };
  }

  return {
    state: "unknown",
    healthy: false,
    reason: `${getLlmProviderLabel(normalized.providerMode)} is configured but not probed yet`,
    providerMode: normalized.providerMode,
    baseUrl: normalized.baseUrl,
    model: normalized.model,
    apiKeyRef: normalized.apiKeyRef,
    latencyMs: null,
    lastCheckedAt: null,
  };
}

export function createDegradedLlmProviderStatus(
  config: LlmConfig,
  reason: string
): LlmProviderStatus {
  return {
    state: "degraded",
    healthy: false,
    reason,
    providerMode: config.providerMode,
    baseUrl: config.baseUrl,
    model: config.model,
    apiKeyRef: config.apiKeyRef,
    latencyMs: null,
    lastCheckedAt: new Date().toISOString(),
  };
}

export function createErrorLlmProviderStatus(
  config: LlmConfig,
  reason: string
): LlmProviderStatus {
  return {
    state: "error",
    healthy: false,
    reason,
    providerMode: config.providerMode,
    baseUrl: config.baseUrl,
    model: config.model,
    apiKeyRef: config.apiKeyRef,
    latencyMs: null,
    lastCheckedAt: new Date().toISOString(),
  };
}

export function createReadyLlmProviderStatus(
  config: LlmConfig,
  reason = "provider configured"
): LlmProviderStatus {
  return {
    state: "ready",
    healthy: true,
    reason,
    providerMode: config.providerMode,
    baseUrl: config.baseUrl,
    model: config.model,
    apiKeyRef: config.apiKeyRef,
    latencyMs: null,
    lastCheckedAt: new Date().toISOString(),
  };
}

export function createSafeLlmAssistResponse(
  task: LlmAssistTask,
  reason: string,
  config?: Partial<LlmConfig>
): LlmAssistResponse {
  const normalized = createDefaultLlmConfig(config ?? {});

  return {
    summary: `LLM unavailable for ${task.kind}: ${reason}`,
    recommendations: [
      "Continue with the deterministic solver path",
      "Show the status in the cockpit instead of blocking the flow",
    ],
    warnings: [
      reason,
      normalized.enabled ? "Fallback executed while provider was configured" : "LLM is disabled by default",
    ],
    confidence: 0,
    usedContext: [],
    latencyMs: 0,
    providerMetadata: {
      providerMode: normalized.providerMode,
      baseUrl: normalized.baseUrl,
      model: normalized.model,
      apiKeyRef: normalized.apiKeyRef,
      taskKind: task.kind,
      safeFallback: true,
    },
  };
}

