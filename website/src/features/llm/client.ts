import { createOpenAICompatibleClient, OpenAICompatibleClient } from "../../lib/openaiCompatible";
import { createDefaultLlmConfig, getLlmTaskRole, getLlmTaskScopes, isLlmTaskAllowed } from "./config";
import { buildLlmMessages, extractAssistantText } from "./prompts";
import { createDefaultLlmProviderStatus, createSafeLlmAssistResponse, createReadyLlmProviderStatus, createDegradedLlmProviderStatus } from "./status";
import { LlmAssistExecution, LlmAssistResponse, LlmAssistTask, LlmConfig, LlmProviderStatus } from "./types";

export interface CreateLlmClientOptions {
  config?: Partial<LlmConfig>;
  resolveApiKey?: (apiKeyRef: string) => Promise<string | null> | string | null;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export interface LlmClient {
  config: LlmConfig;
  status: LlmProviderStatus;
  runTask(task: LlmAssistTask): Promise<LlmAssistExecution>;
  describeTask(task: LlmAssistTask): {
    role: string;
    scopes: string[];
    allowed: boolean;
  };
}

function normalizeProviderStatus(
  config: LlmConfig,
  openAiStatusMode: string,
  reason: string
): LlmProviderStatus {
  if (!config.enabled || config.providerMode === "disabled") {
    return createDefaultLlmProviderStatus(config);
  }

  if (openAiStatusMode === "ready") {
    return createReadyLlmProviderStatus(config, reason);
  }

  return createDegradedLlmProviderStatus(config, reason);
}

function parseStructuredResponse(
  rawText: string,
  config: LlmConfig,
  task: LlmAssistTask
): LlmAssistResponse {
  try {
    const payload = JSON.parse(rawText) as Partial<LlmAssistResponse> & {
      used_context?: string[];
      provider_metadata?: Record<string, unknown>;
    };

    return {
      summary: typeof payload.summary === "string" ? payload.summary : rawText,
      recommendations: Array.isArray(payload.recommendations)
        ? payload.recommendations.filter((item) => typeof item === "string")
        : [],
      warnings: Array.isArray(payload.warnings)
        ? payload.warnings.filter((item) => typeof item === "string")
        : [],
      confidence: typeof payload.confidence === "number" ? payload.confidence : 0.5,
      usedContext: Array.isArray(payload.usedContext)
        ? payload.usedContext.filter((item) => typeof item === "string")
        : Array.isArray(payload.used_context)
          ? payload.used_context.filter((item) => typeof item === "string")
          : [],
      latencyMs: typeof payload.latencyMs === "number" ? payload.latencyMs : 0,
      providerMetadata: payload.providerMetadata ?? payload.provider_metadata ?? {
        model: config.model,
        taskKind: task.kind,
      },
      rawText,
    };
  } catch {
    return {
      summary: rawText || `LLM response for ${task.kind}`,
      recommendations: [],
      warnings: ["The provider did not return structured JSON; using raw text instead."],
      confidence: 0.4,
      usedContext: [],
      latencyMs: 0,
      providerMetadata: {
        model: config.model,
        taskKind: task.kind,
        parsed: false,
      },
      rawText,
    };
  }
}

export function createLlmClient(options: CreateLlmClientOptions = {}): LlmClient {
  const config = createDefaultLlmConfig(options.config ?? {});
  const canUseProvider = config.enabled && config.providerMode !== "disabled";
  const openAiClient: OpenAICompatibleClient | null = canUseProvider
    ? createOpenAICompatibleClient({
        baseUrl: config.baseUrl,
        model: config.model,
        apiKeyRef: config.apiKeyRef || undefined,
        resolveApiKey: options.resolveApiKey,
        fetchImpl: options.fetchImpl,
        timeoutMs: options.timeoutMs,
      })
    : null;

  const status = openAiClient
    ? normalizeProviderStatus(config, openAiClient.status.mode, openAiClient.status.reason)
    : createDefaultLlmProviderStatus(config);

  return {
    config,
    status,
    describeTask(task: LlmAssistTask) {
      return {
        role: getLlmTaskRole(task.kind),
        scopes: task.focusScopes ?? getLlmTaskScopes(task.kind),
        allowed: isLlmTaskAllowed(config, task),
      };
    },
    async runTask(task: LlmAssistTask) {
      if (!config.enabled || config.providerMode === "disabled") {
        return {
          status: createDefaultLlmProviderStatus(config),
          response: createSafeLlmAssistResponse(task, "LLM is disabled", config),
        };
      }

      if (!isLlmTaskAllowed(config, task)) {
        return {
          status: createDegradedLlmProviderStatus(config, "Task blocked by role or scope settings"),
          response: createSafeLlmAssistResponse(
            task,
            "Task blocked by the current role/scope configuration",
            config
          ),
        };
      }

      if (!openAiClient) {
        return {
          status: createDegradedLlmProviderStatus(config, "OpenAI-compatible client unavailable"),
          response: createSafeLlmAssistResponse(task, "Provider client unavailable", config),
        };
      }

      try {
        const startedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
        const messages = buildLlmMessages(task, config);
        const completion = await openAiClient.chatCompletions({
          model: config.model,
          messages,
          temperature: config.temperature,
          max_tokens: config.maxOutputTokens,
          stream: config.streaming,
        });
        const rawText = extractAssistantText(completion.choices[0]?.message?.content);
        const response = parseStructuredResponse(rawText, config, task);
        response.latencyMs = Math.max(
          0,
          Math.round(
            (typeof performance !== "undefined" ? performance.now() : Date.now()) - startedAt
          )
        );

        return {
          status: createReadyLlmProviderStatus(config, "Provider request completed"),
          response,
        };
      } catch (error) {
        const reason = error instanceof Error ? error.message : "Unknown provider error";
        return {
          status: createDegradedLlmProviderStatus(config, reason),
          response: createSafeLlmAssistResponse(task, reason, config),
        };
      }
    },
  };
}

