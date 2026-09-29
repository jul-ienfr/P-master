import { createOpenAICompatibleClient, OpenAICompatibleClient } from "../../lib/openaiCompatible";
import { createDefaultLlmConfig, getLlmTaskRole, getLlmTaskScopes, isLlmTaskAllowed } from "./config";
import { buildLlmMessages, extractAssistantText, DJEV_OUTPUT_QUESTIONS } from "./prompts";
import { createDefaultLlmProviderStatus, createSafeLlmAssistResponse, createReadyLlmProviderStatus, createDegradedLlmProviderStatus } from "./status";
import { LlmAssistExecution, LlmAssistResponse, LlmAssistTask, LlmConfig, LlmProviderStatus, type DjevQuestionKey } from "./types";

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

/**
 * Strict Djev parsing against the 4 System One output schemas declared in
 * `./prompts` (`DJEV_OUTPUT_QUESTIONS`: summary, recommendations, warnings,
 * confidence). Pure function: zero network, zero key, never throws. Every
 * path returns a `DjevParseResult` whose `value` is always a well-typed
 * fail-safe structure by construction (usable without narrowing on `ok`).
 *
 * `parseStructuredResponse` below stays untouched as the legacy fallback for
 * raw-text provider output.
 */

export type DjevSchemaId = DjevQuestionKey;

export interface DjevScoreValue {
  score: number;
  confidence: number | null;
}

export interface DjevChoiceValue {
  choice: string;
  confidence: number | null;
  probabilities: Record<string, number> | null;
}

export interface DjevNoulValue {
  noul: number;
}

export type DjevParsedValue = DjevScoreValue | DjevChoiceValue | DjevNoulValue;

export interface DjevParseOk<T extends DjevParsedValue> {
  ok: true;
  source: "djev";
  schemaId: DjevSchemaId;
  value: T;
}

export interface DjevParseErr<T extends DjevParsedValue> {
  ok: false;
  source: "djev";
  schemaId: DjevSchemaId;
  reason: string;
  /** Fail-safe default, always usable without narrowing on `ok`. */
  value: T;
}

export type DjevParseResult<T extends DjevParsedValue> = DjevParseOk<T> | DjevParseErr<T>;

export const DJEV_SCHEMA_IDS: readonly DjevSchemaId[] = [
  "summary",
  "recommendations",
  "warnings",
  "confidence",
];

export function isDjevSchemaId(value: unknown): value is DjevSchemaId {
  return typeof value === "string" && (DJEV_SCHEMA_IDS as readonly string[]).includes(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asUnitNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return value >= 0 && value <= 1 ? value : null;
}

/** Accept a bare answer or the System One wire envelope `{ answers: { [schemaId]: ... } }`; raw JSON text is parsed, never fetched. */
function unwrapDjevAnswer(schemaId: DjevSchemaId, payload: unknown): unknown {
  let body: unknown = payload;
  if (typeof body === "string") {
    const trimmed = body.trim();
    if (!trimmed) {
      return undefined;
    }
    try {
      body = JSON.parse(trimmed) as unknown;
    } catch {
      return undefined;
    }
  }
  if (isRecord(body) && isRecord(body.answers) && body.answers[schemaId] !== undefined) {
    return body.answers[schemaId];
  }
  return body;
}

function logDjevParse(schemaId: string, ok: boolean, detail: string): void {
  if (typeof console === "undefined") {
    return;
  }
  const line = `DJEV_PARSE | source=djev schema=${schemaId} ${ok ? "ok" : "fail"} ${detail}`;
  if (ok) {
    console.info(line);
  } else {
    console.warn(line);
  }
}

function djevFail<T extends DjevParsedValue>(
  schemaId: DjevSchemaId,
  reason: string,
  fallback: T
): DjevParseErr<T> {
  logDjevParse(schemaId, false, reason);
  return { ok: false, source: "djev", schemaId, reason, value: fallback };
}

function djevOk<T extends DjevParsedValue>(
  schemaId: DjevSchemaId,
  value: T,
  detail: string
): DjevParseOk<T> {
  logDjevParse(schemaId, true, detail);
  return { ok: true, source: "djev", schemaId, value };
}

function parseDjevScore(schemaId: DjevSchemaId, answer: unknown): DjevParseResult<DjevScoreValue> {
  const fallback: DjevScoreValue = { score: 0, confidence: null };
  if (!isRecord(answer)) {
    return djevFail(schemaId, "expected object answer with numeric score", fallback);
  }
  const score = asUnitNumber(answer.score);
  if (score === null) {
    return djevFail(schemaId, "score: expected finite number in [0,1]", fallback);
  }
  const confidence = answer.confidence === undefined ? null : asUnitNumber(answer.confidence);
  if (answer.confidence !== undefined && confidence === null) {
    return djevFail(schemaId, "confidence: expected finite number in [0,1]", fallback);
  }
  return djevOk(schemaId, { score, confidence }, `score=${score.toFixed(2)}`);
}

function parseDjevChoice(schemaId: DjevSchemaId, answer: unknown): DjevParseResult<DjevChoiceValue> {
  const fallback: DjevChoiceValue = { choice: "not stated", confidence: null, probabilities: null };
  const allowed: readonly string[] = DJEV_OUTPUT_QUESTIONS[schemaId].options;
  if (!isRecord(answer)) {
    return djevFail(schemaId, "expected object answer with string choice", fallback);
  }
  const choice = answer.choice;
  if (typeof choice !== "string" || !allowed.includes(choice)) {
    return djevFail(schemaId, `choice: expected one of [${allowed.join("|")}]`, fallback);
  }
  const confidence = answer.confidence === undefined ? null : asUnitNumber(answer.confidence);
  if (answer.confidence !== undefined && confidence === null) {
    return djevFail(schemaId, "confidence: expected finite number in [0,1]", fallback);
  }
  let probabilities: Record<string, number> | null = null;
  if (answer.probabilities !== undefined) {
    if (!isRecord(answer.probabilities)) {
      return djevFail(schemaId, "probabilities: expected object", fallback);
    }
    const entries: Record<string, number> = {};
    for (const [key, val] of Object.entries(answer.probabilities)) {
      const num = asUnitNumber(val);
      if (num === null || !allowed.includes(key)) {
        return djevFail(schemaId, `probabilities: bad entry ${key}`, fallback);
      }
      entries[key] = num;
    }
    probabilities = entries;
  }
  return djevOk(schemaId, { choice, confidence, probabilities }, `choice=${choice}`);
}

function parseDjevNoul(
  schemaId: DjevSchemaId,
  answer: unknown,
  failsafeNoul: 0 | 1
): DjevParseResult<DjevNoulValue> {
  const fallback: DjevNoulValue = { noul: failsafeNoul };
  if (!isRecord(answer)) {
    return djevFail(schemaId, "expected object answer with numeric noul", fallback);
  }
  const noul = asUnitNumber(answer.noul);
  if (noul === null) {
    return djevFail(schemaId, "noul: expected finite number in [0,1]", fallback);
  }
  return djevOk(schemaId, { noul }, `noul=${noul.toFixed(2)}`);
}

/**
 * Strictly validate `payload` against one Djev output schema.
 * Fail-safe by construction: warnings default to high risk (`noul: 1`, never
 * low on unparsed input), confidence defaults to ungrounded (`noul: 0`),
 * summary to `score: 0`, recommendations to `choice: "not stated"`.
 */
export function parseViaDjev(schemaId: "summary", payload: unknown): DjevParseResult<DjevScoreValue>;
export function parseViaDjev(schemaId: "recommendations", payload: unknown): DjevParseResult<DjevChoiceValue>;
export function parseViaDjev(schemaId: "warnings", payload: unknown): DjevParseResult<DjevNoulValue>;
export function parseViaDjev(schemaId: "confidence", payload: unknown): DjevParseResult<DjevNoulValue>;
export function parseViaDjev(schemaId: DjevSchemaId, payload: unknown): DjevParseResult<DjevParsedValue>;
export function parseViaDjev(schemaId: DjevSchemaId, payload: unknown): DjevParseResult<DjevParsedValue> {
  if (!isDjevSchemaId(schemaId)) {
    logDjevParse(String(schemaId), false, "unknown schemaId");
    const fallback: DjevScoreValue = { score: 0, confidence: null };
    return {
      ok: false,
      source: "djev",
      schemaId: "summary",
      reason: `unknown schemaId: ${String(schemaId)}`,
      value: fallback,
    };
  }
  const question = DJEV_OUTPUT_QUESTIONS[schemaId];
  const answer = unwrapDjevAnswer(schemaId, payload);
  switch (question.type) {
    case "score":
      return parseDjevScore(schemaId, answer);
    case "choice":
      return parseDjevChoice(schemaId, answer);
    case "noul":
      return parseDjevNoul(schemaId, answer, schemaId === "warnings" ? 1 : 0);
    default:
      return djevFail(
        schemaId,
        `unsupported question type: ${String((question as { type?: unknown }).type)}`,
        { score: 0, confidence: null }
      );
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

