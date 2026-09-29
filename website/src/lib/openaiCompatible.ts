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

// ---------------------------------------------------------------------------
// Transport Djev (TypeSafe System One), à côté d'OpenAI/Groq.
//
// Sélection via `bot.ai_gate.provider` ("jev" | "djev" | "auto", défaut
// "auto", cf. docs/ai_gate.schema.json) : "djev" et "auto" activent ce
// transport, "jev" le désactive (client désactivé = fail-open).
// Routage : URL loopback LAN prioritaire (défaut http://127.0.0.1:4000),
// repli cloud officiel https://api.typesafe.ai/v1/systemone uniquement si
// `cloudFallback` est vrai ET `offlineMode` est faux.
// Auth : `Authorization: Bearer` résolu via `resolveApiKey(apiKeyEnv)` où
// `apiKeyEnv` est un NOM de variable d'environnement (jamais la valeur en
// dur). Sans clé + endpoint WAN = fail-open SANS appel réseau.
// Timeout borné [500, 60000] ms. `chatCompletions` ne rejette jamais :
// tout échec -> `emptyResponse` (fail-open, miroir de src/bot/djev_gate.py).
// ---------------------------------------------------------------------------

export const DEFAULT_DJEV_CLOUD_URL = "https://api.typesafe.ai/v1/systemone";
export const DEFAULT_DJEV_LAN_URL = "http://127.0.0.1:4000";
export const DEFAULT_DJEV_MODEL = "jev-1.13.0";
export const DEFAULT_DJEV_API_KEY_ENV = "TYPESAFE_API_KEY";
export const DEFAULT_DJEV_TIMEOUT_MS = 5000;
export const MIN_DJEV_TIMEOUT_MS = 500;
export const MAX_DJEV_TIMEOUT_MS = 60000;

export type AiGateProvider = "jev" | "djev" | "auto";

export interface DjevTransportOptions {
  provider?: string;
  offlineMode?: boolean;
  cloudFallback?: boolean;
  model?: string;
  apiKeyEnv?: string;
  lanUrl?: string;
  cloudUrl?: string;
  baseUrl?: string;
  timeoutMs?: number;
  timeoutS?: number;
  resolveApiKey?: (apiKeyRef: string) => Promise<string | null> | string | null;
  fetchImpl?: typeof fetch;
  defaultHeaders?: Record<string, string>;
}

interface DjevEndpointPlan {
  url: string;
  skippedReason?: string;
}

function asDjevRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
}

function asDjevString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

function asDjevBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function normalizeAiGateProvider(value: unknown): AiGateProvider {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (normalized === "jev" || normalized === "djev" || normalized === "auto") {
    return normalized;
  }
  return "auto";
}

export function isLoopbackUrl(url: string): boolean {
  const raw = (url ?? "").trim();
  if (!raw) {
    return false;
  }
  try {
    const withScheme = raw.includes("://") ? raw : `http://${raw}`;
    const host = new URL(withScheme).hostname.trim().toLowerCase().replace(/^\[|\]$/g, "");
    return host === "127.0.0.1" || host === "localhost" || host === "::1";
  } catch {
    return false;
  }
}

export function clampDjevTimeoutMs(value: unknown): number {
  const parsed = typeof value === "number" && Number.isFinite(value)
    ? value
    : DEFAULT_DJEV_TIMEOUT_MS;
  if (parsed < MIN_DJEV_TIMEOUT_MS) {
    return MIN_DJEV_TIMEOUT_MS;
  }
  if (parsed > MAX_DJEV_TIMEOUT_MS) {
    return MAX_DJEV_TIMEOUT_MS;
  }
  return Math.round(parsed);
}

/**
 * Normalise un bloc `bot.ai_gate` brut (clés camelCase ou snake_case, bloc
 * `djev` imbriqué optionnel) ou des `DjevTransportOptions` déjà construites
 * vers des options effectives. Les résolveurs (`resolveApiKey`, `fetchImpl`)
 * et `defaultHeaders` sont transmis tels quels (jamais lus depuis du JSON).
 */
export function normalizeAiGateDjevOptions(rawValue: unknown): DjevTransportOptions {
  const raw = asDjevRecord(rawValue);
  const sub = asDjevRecord(raw.djev);

  const timeoutMsRaw = sub.timeoutMs ?? sub.timeout_ms ?? raw.timeoutMs ?? raw.timeout_ms;
  const timeoutSRaw = sub.timeoutS ?? sub.timeout_s ?? raw.timeoutS ?? raw.timeout_s;
  const timeoutMs = clampDjevTimeoutMs(
    typeof timeoutMsRaw === "number"
      ? timeoutMsRaw
      : typeof timeoutSRaw === "number"
        ? timeoutSRaw * 1000
        : DEFAULT_DJEV_TIMEOUT_MS
  );

  const rawBase = sub.baseUrl ?? sub.base_url ?? raw.baseUrl ?? raw.base_url;
  const rawHeaders = asDjevRecord(raw.defaultHeaders);
  const hasStringHeaders = Object.values(rawHeaders).every((entry) => typeof entry === "string");

  return {
    provider: normalizeAiGateProvider(raw.provider ?? sub.provider),
    offlineMode: asDjevBoolean(
      sub.offlineMode ?? sub.offline_mode ?? raw.offlineMode ?? raw.offline_mode,
      false
    ),
    cloudFallback: asDjevBoolean(
      sub.cloudFallback ?? sub.cloud_fallback ?? raw.cloudFallback ?? raw.cloud_fallback,
      false
    ),
    model: asDjevString(sub.model ?? raw.model, DEFAULT_DJEV_MODEL),
    apiKeyEnv: asDjevString(
      sub.apiKeyEnv ?? sub.api_key_env ?? raw.apiKeyEnv ?? raw.api_key_env,
      DEFAULT_DJEV_API_KEY_ENV
    ),
    lanUrl: asDjevString(
      sub.lanUrl ?? sub.lan_url ?? raw.lanUrl ?? raw.lan_url,
      DEFAULT_DJEV_LAN_URL
    ),
    cloudUrl: asDjevString(
      sub.cloudUrl ?? sub.cloud_url ?? sub.baseUrl ?? sub.base_url,
      DEFAULT_DJEV_CLOUD_URL
    ),
    baseUrl: typeof rawBase === "string" ? rawBase.trim() : "",
    timeoutMs,
    resolveApiKey: typeof raw.resolveApiKey === "function"
      ? (raw.resolveApiKey as DjevTransportOptions["resolveApiKey"])
      : undefined,
    fetchImpl: typeof raw.fetchImpl === "function"
      ? (raw.fetchImpl as DjevTransportOptions["fetchImpl"])
      : undefined,
    defaultHeaders: hasStringHeaders && Object.keys(rawHeaders).length > 0
      ? (rawHeaders as Record<string, string>)
      : undefined,
  };
}

function planDjevEndpoints(
  resolved: DjevTransportOptions,
  lanUrl: string,
  cloudUrl: string,
  primary: string
): DjevEndpointPlan[] {
  const candidates = [primary];
  if (resolved.cloudFallback && !resolved.offlineMode && cloudUrl && cloudUrl !== primary) {
    candidates.push(cloudUrl);
  }
  void lanUrl;
  return candidates.map((url) => {
    if (!url) {
      return { url, skippedReason: "empty url" };
    }
    if (resolved.offlineMode && !isLoopbackUrl(url)) {
      return { url, skippedReason: "fail-open: offline_mode, WAN refused (no network call)" };
    }
    return { url };
  });
}

export function createDjevOpenAICompatibleClient(
  options: DjevTransportOptions = {}
): OpenAICompatibleClient {
  const resolved = normalizeAiGateDjevOptions(options);
  const provider = normalizeAiGateProvider(resolved.provider);
  const model = resolved.model?.trim() ? resolved.model.trim() : DEFAULT_DJEV_MODEL;
  const apiKeyEnv = resolved.apiKeyEnv?.trim()
    ? resolved.apiKeyEnv.trim()
    : DEFAULT_DJEV_API_KEY_ENV;
  const timeoutMs = clampDjevTimeoutMs(resolved.timeoutMs);
  const lanUrl = resolved.lanUrl?.trim() ? resolved.lanUrl.trim() : DEFAULT_DJEV_LAN_URL;
  const cloudUrl = resolved.cloudUrl?.trim() ? resolved.cloudUrl.trim() : DEFAULT_DJEV_CLOUD_URL;
  const explicitBase = resolved.baseUrl?.trim() ? resolved.baseUrl.trim() : "";
  // LAN loopback prioritaire ; base_url explicite seulement si le LAN est vide.
  const primary = lanUrl || explicitBase || DEFAULT_DJEV_LAN_URL;
  const plans = planDjevEndpoints(resolved, lanUrl, cloudUrl, primary);
  const usable = plans.filter((plan) => !plan.skippedReason);
  const statusBaseUrl = usable[0]?.url ?? primary;

  if (provider === "jev") {
    return {
      status: {
        mode: "disabled",
        reason: "ai_gate.provider=jev, djev transport not selected (fail-open)",
        baseUrl: statusBaseUrl,
        model,
        apiKeyRef: apiKeyEnv,
        healthy: false,
      },
      async chatCompletions() {
        return emptyResponse(model);
      },
    };
  }

  if (usable.length === 0) {
    return {
      status: {
        mode: "disabled",
        reason: `djev: no usable endpoint (${plans.map((plan) => `${plan.url || "(empty)"}: ${plan.skippedReason ?? "skipped"}`).join("; ") || "no endpoint"})`,
        baseUrl: statusBaseUrl,
        model,
        apiKeyRef: apiKeyEnv,
        healthy: false,
      },
      async chatCompletions(request: OpenAICompatibleChatCompletionRequest) {
        return emptyResponse(request.model ?? model);
      },
    };
  }

  const wanPlanned = usable.some((plan) => !isLoopbackUrl(plan.url));
  const ready = !wanPlanned || Boolean(resolved.resolveApiKey);

  const status: OpenAICompatibleClientStatus = {
    mode: ready ? "ready" : "missing_api_key",
    reason: ready
      ? `djev client configured (LAN first: ${usable[0].url}${usable.length > 1 ? `, cloud fallback: ${usable.slice(1).map((plan) => plan.url).join(", ")}` : ", no cloud fallback"})`
      : "djev: WAN endpoint planned but no resolveApiKey was supplied (fail-open without key)",
    baseUrl: statusBaseUrl,
    model,
    apiKeyRef: apiKeyEnv,
    healthy: ready,
  };

  return {
    status,
    async chatCompletions(request: OpenAICompatibleChatCompletionRequest) {
      const activeModel = request.model ?? model;
      if (!request.messages || request.messages.length === 0) {
        return emptyResponse(activeModel);
      }

      let apiKey: string | null = null;
      if (apiKeyEnv && resolved.resolveApiKey) {
        try {
          apiKey = await resolved.resolveApiKey(apiKeyEnv);
        } catch {
          apiKey = null;
        }
      }

      for (const plan of plans) {
        if (plan.skippedReason || !plan.url) {
          continue;
        }
        // Cloud sans clé : on ne tente même pas l'appel (fail-open sans réseau).
        if (!isLoopbackUrl(plan.url) && !apiKey) {
          continue;
        }
        try {
          const inner = createOpenAICompatibleClient({
            baseUrl: plan.url,
            model,
            apiKeyRef: apiKey ? apiKeyEnv : undefined,
            resolveApiKey: apiKey ? async () => apiKey : undefined,
            fetchImpl: resolved.fetchImpl,
            timeoutMs,
            defaultHeaders: resolved.defaultHeaders,
          });
          return await inner.chatCompletions(request);
        } catch {
          // Échec LAN -> repli cloud si planifié, sinon fail-open ci-dessous.
        }
      }
      return emptyResponse(activeModel);
    },
  };
}
