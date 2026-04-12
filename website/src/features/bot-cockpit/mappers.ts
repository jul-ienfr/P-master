import { createDefaultBotCockpitPayload } from "./fixtures";
import {
  createBotCockpitSummary,
  getBotCockpitOperatorTone,
  getBotCockpitRuntimeTone,
  summarizeBotCockpitAlerts,
} from "./status";
import type {
  BotCockpitAlertItem,
  BotCockpitAlertKind,
  BotCockpitAlertSeverity,
  BotCockpitCardSnapshot,
  BotCockpitConnectionSnapshot,
  BotCockpitDecisionAction,
  BotCockpitDecisionSnapshot,
  BotCockpitDecisionSource,
  BotCockpitOperatorMode,
  BotCockpitPayload,
  BotCockpitRuntimeSnapshot,
  BotCockpitRuntimeSource,
  BotCockpitRuntimeState,
  BotCockpitSpotSnapshot,
  BotCockpitState,
  BotCockpitSurface,
} from "./types";

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : {};
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizeOperatorMode(value: unknown): BotCockpitOperatorMode {
  switch (value) {
    case "assist":
    case "shadow":
    case "manual_override":
    case "diagnostic":
    case "observe_only":
      return value;
    default:
      return "observe_only";
  }
}

function normalizeRuntimeState(value: unknown): BotCockpitRuntimeState {
  switch (value) {
    case "ready":
    case "streaming":
    case "degraded":
    case "offline":
    case "error":
    case "idle":
      return value;
    default:
      return "idle";
  }
}

function normalizeRuntimeSource(value: unknown): BotCockpitRuntimeSource {
  switch (value) {
    case "tauri":
    case "local_rest":
    case "browser_stub":
    case "legacy":
      return value;
    default:
      return "unknown";
  }
}

function normalizeDecisionSource(value: unknown): BotCockpitDecisionSource {
  switch (value) {
    case "native":
    case "http":
    case "fallback":
    case "legacy":
    case "browser_stub":
      return value;
    default:
      return "unknown";
  }
}

function normalizeSurface(value: unknown): BotCockpitSurface {
  switch (value) {
    case "bot_cockpit":
    case "solver_studio":
    case "replay_analytics":
    case "config_lab":
      return value;
    default:
      return "bot_cockpit";
  }
}

function normalizeAlertSeverity(value: unknown): BotCockpitAlertSeverity {
  switch (value) {
    case "success":
    case "warning":
    case "error":
      return value;
    default:
      return "info";
  }
}

function normalizeAlertSource(
  value: unknown
): BotCockpitRuntimeSource | BotCockpitDecisionSource {
  switch (value) {
    case "tauri":
    case "local_rest":
    case "browser_stub":
    case "legacy":
      return value;
    case "native":
    case "http":
    case "fallback":
      return value;
    default:
      return "unknown";
  }
}

function normalizeAlertKind(value: unknown): BotCockpitAlertKind {
  switch (value) {
    case "runtime":
    case "ocr":
    case "solver":
    case "decision":
    case "fallback":
    case "network":
    case "operator":
    case "range":
    case "security":
    case "system":
      return value;
    default:
      return "unknown";
  }
}

function normalizeCardSnapshot(value: unknown): BotCockpitCardSnapshot {
  if (typeof value === "string") {
    const compact = value.replace(/\s+/g, "").replace(/^10/i, "T");
    return {
      rank: compact.slice(0, compact.length - 1).toUpperCase(),
      suit: compact.slice(-1).toLowerCase(),
      label: compact,
    };
  }

  const raw = asRecord(value);
  return {
    rank: asString(raw.rank),
    suit: asString(raw.suit),
    label: asString(raw.label, `${asString(raw.rank)}${asString(raw.suit)}`),
  };
}

function normalizeCardList(value: unknown): BotCockpitCardSnapshot[] {
  return Array.isArray(value) ? value.map((card) => normalizeCardSnapshot(card)) : [];
}

function normalizeDecisionAction(value: unknown, chosenAction: string): BotCockpitDecisionAction {
  const raw = asRecord(value);
  const name = asString(raw.name);
  return {
    name,
    label: asString(raw.label, name),
    size: typeof raw.size === "number" && Number.isFinite(raw.size) ? raw.size : null,
    frequency: asNumber(raw.frequency),
    ev: asNumber(raw.ev),
    isRecommended:
      asBoolean(raw.is_recommended) ||
      asBoolean(raw.isRecommended) ||
      (name.length > 0 && name === chosenAction),
  };
}

function normalizeAlertItem(value: unknown, index: number): BotCockpitAlertItem {
  if (typeof value === "string") {
    return {
      id: `alert-${index}`,
      kind: "system",
      severity: "info",
      title: value,
      message: value,
      createdAt: new Date(0).toISOString(),
      source: "browser_stub",
      dismissible: true,
      acknowledged: false,
      context: {},
    };
  }

  const raw = asRecord(value);
  const title = asString(raw.title, `Alert ${index + 1}`);
  const message = asString(raw.message, title);
  return {
    id: asString(raw.id, `alert-${index}`),
    kind: normalizeAlertKind(raw.kind),
    severity: normalizeAlertSeverity(raw.severity),
    title,
    message,
    createdAt: asString(raw.createdAt, new Date(0).toISOString()),
    source: normalizeAlertSource(raw.source),
    dismissible: asBoolean(raw.dismissible, true),
    acknowledged: asBoolean(raw.acknowledged, false),
    context: asRecord(raw.context),
  };
}

function normalizeConnectionSnapshot(value: unknown): BotCockpitConnectionSnapshot {
  const raw = asRecord(value);
  const transport = asString(raw.transport, "browser_stub");
  return {
    transport:
      transport === "tauri" ||
      transport === "local_rest" ||
      transport === "browser_stub" ||
      transport === "offline"
        ? transport
        : "browser_stub",
    endpoint: asString(raw.endpoint),
    reachable: asBoolean(raw.reachable, false),
    httpStatus: typeof raw.httpStatus === "number" && Number.isFinite(raw.httpStatus) ? raw.httpStatus : null,
    latencyMs: typeof raw.latencyMs === "number" && Number.isFinite(raw.latencyMs) ? raw.latencyMs : null,
    lastCheckedAt: asString(raw.lastCheckedAt, new Date(0).toISOString()),
  };
}

function normalizeSpotSnapshot(value: unknown): BotCockpitSpotSnapshot {
  const raw = asRecord(value);
  const heroCards = normalizeCardList(raw.heroCards ?? raw.hero_cards);
  const board = normalizeCardList(raw.board);
  return {
    id: asString(raw.id, "bot-cockpit-spot"),
    label: asString(raw.label, "Bot cockpit spot"),
    street: raw.street === "flop" || raw.street === "turn" || raw.street === "river" ? raw.street : "preflop",
    heroPosition: asString(raw.heroPosition, ""),
    heroCards,
    board,
    heroRange: asString(raw.heroRange, ""),
    villainRanges: asStringArray(raw.villainRanges),
    legalActions: asStringArray(raw.legalActions),
    actionHistory: asStringArray(raw.actionHistory),
    pot: asNumber(raw.pot),
    effectiveStack: asNumber(raw.effectiveStack),
    numPlayers: asNumber(raw.numPlayers, 2),
    source: normalizeRuntimeSource(raw.source),
    tableName: asString(raw.tableName, ""),
    handId: asString(raw.handId, ""),
    ranges: asRecord(raw.ranges),
    ocr: asRecord(raw.ocr),
    notes: asStringArray(raw.notes),
  };
}

function normalizeDecisionSnapshot(value: unknown): BotCockpitDecisionSnapshot {
  const raw = asRecord(value);
  const chosenAction = asString(raw.chosenAction ?? raw.chosen_action);
  const actionsRaw = Array.isArray(raw.actions) ? raw.actions : [];
  return {
    chosenAction,
    actions: actionsRaw.map((action) => normalizeDecisionAction(action, chosenAction)),
    heroEv: asNumber(raw.heroEv ?? raw.hero_ev),
    exploitability: asNumber(raw.exploitability),
    source: normalizeDecisionSource(raw.source),
    warnings: asStringArray(raw.warnings),
    latencyMs: asNumber(raw.latencyMs ?? raw.elapsedMs ?? raw.elapsed_ms),
    cacheHit: asBoolean(raw.cacheHit ?? raw.cache_hit),
    confidence: typeof raw.confidence === "number" && Number.isFinite(raw.confidence) ? raw.confidence : 0,
    presetId: asString(raw.presetId ?? raw.preset_id, "srp_hu_100bb"),
    rationale: asString(raw.rationale, ""),
  };
}

function normalizeRuntimeSnapshot(rawValue: unknown): BotCockpitRuntimeSnapshot {
  const envelope = asRecord(rawValue);
  const runtime = asRecord(envelope.runtime ?? envelope.snapshot ?? envelope.payload);
  const raw = { ...runtime, ...envelope };

  return {
    status: normalizeRuntimeState(raw.status),
    source: normalizeRuntimeSource(raw.source),
    operatorMode: normalizeOperatorMode(raw.operatorMode ?? raw.operator_mode),
    surface: normalizeSurface(raw.surface),
    spot: normalizeSpotSnapshot(raw.spot),
    decision: normalizeDecisionSnapshot(raw.decision),
    alerts: Array.isArray(raw.alerts) ? raw.alerts.map((alert, index) => normalizeAlertItem(alert, index)) : [],
    connection: normalizeConnectionSnapshot(raw.connection),
    sampleId: asString(raw.sampleId ?? raw.sample_id, "bot-cockpit-sample"),
    title: asString(raw.title, "Bot cockpit sample"),
    description: asString(raw.description, ""),
    lastUpdatedAt: asString(raw.lastUpdatedAt ?? raw.last_updated_at, new Date(0).toISOString()),
    notes: asStringArray(raw.notes),
    metrics: asRecord(raw.metrics),
  };
}

function cloneRuntimeSnapshot(runtime: BotCockpitRuntimeSnapshot): BotCockpitRuntimeSnapshot {
  return {
    ...runtime,
    spot: {
      ...runtime.spot,
      heroCards: runtime.spot.heroCards.map((card) => ({ ...card })),
      board: runtime.spot.board.map((card) => ({ ...card })),
      villainRanges: [...runtime.spot.villainRanges],
      legalActions: [...runtime.spot.legalActions],
      actionHistory: [...runtime.spot.actionHistory],
      ranges: { ...runtime.spot.ranges },
      ocr: { ...runtime.spot.ocr },
      notes: [...runtime.spot.notes],
    },
    decision: {
      ...runtime.decision,
      actions: runtime.decision.actions.map((action) => ({ ...action })),
      warnings: [...runtime.decision.warnings],
    },
    alerts: runtime.alerts.map((alert) => ({
      ...alert,
      context: { ...alert.context },
    })),
    connection: { ...runtime.connection },
    notes: [...runtime.notes],
    metrics: { ...runtime.metrics },
  };
}

export function mapBotCockpitPayloadToState(
  payload: BotCockpitPayload | unknown
): BotCockpitState {
  const raw = asRecord(payload);
  const runtime = normalizeRuntimeSnapshot(raw.runtime ?? raw.snapshot ?? raw);
  const alertSummary = summarizeBotCockpitAlerts(runtime.alerts);
  const statusTone = getBotCockpitRuntimeTone(runtime.status);
  const operatorTone = getBotCockpitOperatorTone(runtime.operatorMode);

  return {
    ...cloneRuntimeSnapshot(runtime),
    sampleId: asString(raw.sampleId, runtime.sampleId),
    title: asString(raw.title, runtime.title),
    description: asString(raw.description, runtime.description),
    statusTone,
    operatorTone,
    alertSummary,
    summary: createBotCockpitSummary(runtime.status, runtime.operatorMode, alertSummary),
  };
}

export function mapRuntimeSnapshotToBotCockpitState(
  snapshot: unknown
): BotCockpitState {
  return mapBotCockpitPayloadToState(snapshot);
}

export function createDefaultBotCockpitState(): BotCockpitState {
  return mapBotCockpitPayloadToState(createDefaultBotCockpitPayload());
}

export function mapBotCockpitStateToRuntimeSnapshot(
  state: BotCockpitState
): BotCockpitRuntimeSnapshot {
  return cloneRuntimeSnapshot({
    status: state.status,
    source: state.source,
    operatorMode: state.operatorMode,
    surface: state.surface,
    spot: state.spot,
    decision: state.decision,
    alerts: state.alerts,
    connection: state.connection,
    sampleId: state.sampleId,
    title: state.title,
    description: state.description,
    lastUpdatedAt: state.lastUpdatedAt,
    notes: state.notes,
    metrics: state.metrics,
  });
}

export function mapRuntimeSnapshotToBotCockpitPayload(
  snapshot: unknown
): BotCockpitPayload {
  const state = mapRuntimeSnapshotToBotCockpitState(snapshot);
  return {
    sampleId: state.sampleId,
    title: state.title,
    description: state.description,
    runtime: mapBotCockpitStateToRuntimeSnapshot(state),
  };
}
