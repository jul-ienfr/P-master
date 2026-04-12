import { LlmAssistTask, LlmConfig, LlmScope } from "./types";

export interface SanitizedLlmContext {
  kind: string;
  title?: string;
  instruction?: string;
  spot?: Record<string, unknown>;
  decision?: Record<string, unknown>;
  replay?: Record<string, unknown>;
  ui?: Record<string, unknown>;
  allowedScopes: LlmScope[];
}

function cloneDefinedObject(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }

  const copy: Record<string, unknown> = {};
  for (const key of Object.keys(value as Record<string, unknown>)) {
    const entry = (value as Record<string, unknown>)[key];
    if (entry !== undefined && entry !== null) {
      copy[key] = entry;
    }
  }
  return copy;
}

function redactString(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  if (trimmed.length <= 16) {
    return "[redacted]";
  }

  return `${trimmed.slice(0, 4)}…${trimmed.slice(-4)}`;
}

export function getAllowedScopes(config: LlmConfig, requestedScopes: LlmScope[]): LlmScope[] {
  return requestedScopes.filter((scope) => config.contextScopesEnabled[scope]);
}

export function sanitizeTaskForPrivacy(task: LlmAssistTask, config: LlmConfig): SanitizedLlmContext {
  const requestedScopes = task.focusScopes ?? [];
  const allowedScopes = getAllowedScopes(config, requestedScopes);
  const strictLocal = config.privacyMode === "strict_local";
  const redactedRemote = config.privacyMode === "redacted_remote";

  const include = (scope: LlmScope): boolean => allowedScopes.includes(scope);

  return {
    kind: task.kind,
    title: task.title,
    instruction: task.instruction,
    allowedScopes,
    spot: include("spot") && task.spot
      ? strictLocal
        ? cloneDefinedObject(task.spot as unknown as Record<string, unknown>)
        : redactedRemote
          ? {
              street: task.spot.street,
              heroPosition: task.spot.heroPosition,
              pot: task.spot.pot,
              effectiveStack: task.spot.effectiveStack,
              numPlayers: task.spot.numPlayers,
              legalActions: task.spot.legalActions,
              actionHistory: task.spot.actionHistory,
              source: task.spot.source,
              heroCards: task.spot.heroCards?.map((card) => ({
                rank: card.rank,
                suit: card.suit,
                label: card.label ? redactString(card.label) : undefined,
              })),
              board: task.spot.board?.map((card) => ({
                rank: card.rank,
                suit: card.suit,
                label: card.label ? redactString(card.label) : undefined,
              })),
            }
          : cloneDefinedObject(task.spot as unknown as Record<string, unknown>)
      : undefined,
    decision: include("decision") && task.decision
      ? cloneDefinedObject(task.decision as unknown as Record<string, unknown>)
      : undefined,
    replay: include("replay") && task.replay
      ? cloneDefinedObject(task.replay as unknown as Record<string, unknown>)
      : undefined,
    ui: include("settings") || include("runtime") || include("ocr") || include("fallback")
      ? cloneDefinedObject(task.ui as unknown as Record<string, unknown>)
      : undefined,
  };
}
