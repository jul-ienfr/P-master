export type OpenAICompatibleRole = "system" | "user" | "assistant" | "tool";

export interface OpenAICompatibleMessage {
  role: OpenAICompatibleRole;
  content: string;
  name?: string;
}

export interface OpenAICompatibleChatCompletionRequest {
  messages: OpenAICompatibleMessage[];
  model?: string;
  temperature?: number;
  max_tokens?: number;
  stream?: boolean;
  extraBody?: Record<string, unknown>;
}

export interface OpenAICompatibleChatCompletionChoice {
  index: number;
  message: {
    role: "assistant";
    content: string | null;
  };
  finish_reason?: string | null;
}

export interface OpenAICompatibleChatCompletionResponse {
  id?: string;
  object?: string;
  created?: number;
  model?: string;
  choices: OpenAICompatibleChatCompletionChoice[];
  raw?: unknown;
}

export interface OpenAICompatibleClientOptions {
  baseUrl: string;
  model: string;
  apiKeyRef?: string;
  resolveApiKey?: (apiKeyRef: string) => Promise<string | null> | string | null;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  defaultHeaders?: Record<string, string>;
}

export interface OpenAICompatibleClientStatus {
  mode: "ready" | "disabled" | "missing_api_key" | "invalid_config" | "error";
  reason: string;
  baseUrl: string;
  model: string;
  apiKeyRef?: string;
  healthy: boolean;
}

export interface OpenAICompatibleClient {
  status: OpenAICompatibleClientStatus;
  chatCompletions(
    request: OpenAICompatibleChatCompletionRequest
  ): Promise<OpenAICompatibleChatCompletionResponse>;
}

const defaultFetch = typeof fetch === "function" ? fetch.bind(globalThis) : undefined;

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, "");
}

function buildUrl(baseUrl: string, path: string): string {
  const normalizedBase = normalizeBaseUrl(baseUrl);
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`;
}

function timeoutSignal(timeoutMs?: number): AbortSignal | undefined {
  if (!timeoutMs || timeoutMs <= 0 || typeof AbortController === "undefined") {
    return undefined;
  }

  const controller = new AbortController();
  setTimeout(() => controller.abort(), timeoutMs);
  return controller.signal;
}

function emptyResponse(model: string): OpenAICompatibleChatCompletionResponse {
  return {
    model,
    choices: [
      {
        index: 0,
        message: {
          role: "assistant",
          content: "",
        },
        finish_reason: "stop",
      },
    ],
  };
}

export function createDisabledOpenAICompatibleClient(
  baseUrl: string,
  model: string,
  reason = "provider disabled"
): OpenAICompatibleClient {
  return {
    status: {
      mode: "disabled",
      reason,
      baseUrl,
      model,
      healthy: false,
    },
    async chatCompletions() {
      return emptyResponse(model);
    },
  };
}

export function createOpenAICompatibleClient(
  options: OpenAICompatibleClientOptions
): OpenAICompatibleClient {
  const fetchImpl = options.fetchImpl ?? defaultFetch;
  const normalizedBaseUrl = normalizeBaseUrl(options.baseUrl);
  const hasValidBaseUrl = normalizedBaseUrl.length > 0;
  const hasModel = options.model.trim().length > 0;

  if (!hasValidBaseUrl || !hasModel) {
    return {
      status: {
        mode: "invalid_config",
        reason: "base_url or model is missing",
        baseUrl: options.baseUrl,
        model: options.model,
        apiKeyRef: options.apiKeyRef,
        healthy: false,
      },
      async chatCompletions() {
        return emptyResponse(options.model);
      },
    };
  }

  if (!fetchImpl) {
    return {
      status: {
        mode: "error",
        reason: "fetch is unavailable in this runtime",
        baseUrl: normalizedBaseUrl,
        model: options.model,
        apiKeyRef: options.apiKeyRef,
        healthy: false,
      },
      async chatCompletions() {
        return emptyResponse(options.model);
      },
    };
  }

  return {
    status: {
      mode: options.apiKeyRef && !options.resolveApiKey ? "missing_api_key" : "ready",
      reason: options.apiKeyRef && !options.resolveApiKey
        ? "api key reference provided but no resolver was supplied"
        : "client configured",
      baseUrl: normalizedBaseUrl,
      model: options.model,
      apiKeyRef: options.apiKeyRef,
      healthy: !options.apiKeyRef || Boolean(options.resolveApiKey),
    },
    async chatCompletions(request: OpenAICompatibleChatCompletionRequest) {
      const apiKey = options.apiKeyRef && options.resolveApiKey
        ? await options.resolveApiKey(options.apiKeyRef)
        : null;

      if (options.apiKeyRef && !apiKey) {
        throw new Error("OpenAI-compatible client: api key could not be resolved");
      }

      const response = await fetchImpl(buildUrl(normalizedBaseUrl, "/chat/completions"), {
        method: "POST",
        signal: timeoutSignal(options.timeoutMs),
        headers: {
          "content-type": "application/json",
          ...(apiKey ? { authorization: `Bearer ${apiKey}` } : {}),
          ...(options.defaultHeaders ?? {}),
        },
        body: JSON.stringify({
          model: request.model ?? options.model,
          messages: request.messages,
          temperature: request.temperature,
          max_tokens: request.max_tokens,
          stream: false,
          ...request.extraBody,
        }),
      });

      if (!response.ok) {
        const body = await response.text();
        throw new Error(
          `OpenAI-compatible client request failed (${response.status} ${response.statusText}): ${body}`
        );
      }

      const payload = (await response.json()) as OpenAICompatibleChatCompletionResponse;
      return {
        ...payload,
        raw: payload,
        model: payload.model ?? request.model ?? options.model,
      };
    },
  };
}
