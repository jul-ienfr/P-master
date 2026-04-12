const LOCAL_BOT_COCKPIT_URLS = [
  "http://127.0.0.1:8080/bot-cockpit/payload",
  "http://127.0.0.1:8080/runtime-snapshot",
  "http://127.0.0.1:8005/bot-cockpit/payload",
  "http://127.0.0.1:8005/runtime-snapshot",
  "/bot-cockpit/payload",
  "/runtime-snapshot",
];
const LOCAL_BOT_COCKPIT_HISTORY_URLS = [
  "http://127.0.0.1:8080/runtime-history",
  "http://127.0.0.1:8005/runtime-history",
  "/runtime-history",
];
const LOCAL_BOT_COCKPIT_REFRESH_URLS = [
  "http://127.0.0.1:8080/bot-cockpit/refresh",
  "http://127.0.0.1:8005/bot-cockpit/refresh",
  "/bot-cockpit/refresh",
  ...LOCAL_BOT_COCKPIT_URLS,
];
const LOCAL_BOT_COCKPIT_OPERATOR_URLS = [
  "http://127.0.0.1:8080/bot-cockpit/operator",
  "http://127.0.0.1:8005/bot-cockpit/operator",
  "/bot-cockpit/operator",
];
const DEFAULT_TIMEOUT_MS = 800;
const DESKTOP_RUNTIME_RETRY_DELAYS_MS = [0, 350, 800, 1_600, 3_000];

type UnknownRecord = Record<string, unknown>;

type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

export type BotCockpitState = "live" | "degraded" | "offline" | "error";

export type BotCockpitSource = "tauri" | "local_rest" | "fallback";

export type BotCockpitWarning =
  | "host_unavailable"
  | "tauri_command_missing"
  | "runtime_unavailable"
  | "runtime_degraded"
  | "runtime_offline"
  | "payload_incomplete"
  | "ocr_low_confidence"
  | "fallback_used"
  | "manual_override"
  | "unknown"
  | (string & {});

export interface BotCockpitTransportMeta {
  endpoint: string;
  source: BotCockpitSource;
  reachable: boolean;
  httpStatus: number | null;
}

export interface BotCockpitLlmSnapshot {
  enabled: boolean;
  providerMode: string;
  baseUrl: string;
  model: string;
  privacyMode: string;
}

export interface BotCockpitRuntimeMetrics {
  decisionCount: number;
  blockedCount: number;
  fallbackCount: number;
  blockRate: number;
  fallbackRate: number;
  rollingLatencyMs: number;
  decisionRate: number;
  windowSize: number;
}

export interface BotCockpitRuntimeSnapshot {
  appName: string;
  version: string;
  runtime: string;
  devMode: boolean;
  httpFallbackEnabled: boolean;
  healthy: boolean;
  status: string;
  uptimeMs: number;
  llm: BotCockpitLlmSnapshot;
  metrics: BotCockpitRuntimeMetrics;
}

export interface BotCockpitSpotSnapshot {
  street: "preflop" | "flop" | "turn" | "river";
  heroPosition: string | null;
  heroSeatId: string | null;
  pot: number;
  effectiveStack: number;
  numPlayers: number;
  board: string[];
  heroCards: string[];
  actionHistory: string[];
  legalActions: string[];
  ranges: Record<string, unknown>;
  source: string;
  metadata: Record<string, unknown>;
  ocrMetadata: Record<string, unknown>;
}

export interface BotCockpitDecisionAlternative {
  name: string;
  size: number | null;
  frequency: number;
  ev: number;
  isRecommended: boolean;
}

export interface BotCockpitDecisionSnapshot {
  chosenAction: string;
  source: "native" | "http" | "fallback" | "legacy" | string;
  alternatives: BotCockpitDecisionAlternative[];
  heroEv: number;
  exploitability: number;
  warnings: BotCockpitWarning[];
  latencyMs: number;
  confidence: number;
  gateConfidence: number;
  observedHands: number;
  metadata: Record<string, unknown>;
}

export interface BotCockpitOcrSnapshot {
  confidence: number;
  drift: string;
  frameLabel: string;
  notes: string[];
  source: string;
  mode?: string;
  selectedEngine?: string;
  loadedEngines?: string[];
  requestedEngines?: string[];
  agreement?: string;
  selectedConfidence?: number;
  engineScores?: Record<string, number>;
  candidates?: Array<Record<string, unknown>>;
}

export interface BotCockpitSignal {
  label: string;
  value: string;
  note?: string;
}

export interface BotCockpitOperatorSnapshot {
  profileName: string;
  surface: string;
  captureSource: string;
  autoRefreshEnabled: boolean;
  shadowModeEnabled: boolean;
  manualOverrideEnabled: boolean;
  paused: boolean;
  status: string;
}

export interface BotCockpitPayload {
  state: BotCockpitState;
  source: BotCockpitSource;
  message: string;
  runtime: BotCockpitRuntimeSnapshot;
  spot: BotCockpitSpotSnapshot;
  decision: BotCockpitDecisionSnapshot;
  ocr: BotCockpitOcrSnapshot;
  operator: BotCockpitOperatorSnapshot;
  signals: BotCockpitSignal[];
  warnings: BotCockpitWarning[];
  transport: BotCockpitTransportMeta;
  refreshedAt: string;
  notes: string[];
  raw: unknown;
}

export interface BotCockpitPayloadOverrides {
  state?: BotCockpitState;
  source?: BotCockpitSource;
  message?: string;
  runtime?: Partial<BotCockpitRuntimeSnapshot>;
  spot?: Partial<BotCockpitSpotSnapshot>;
  decision?: Partial<BotCockpitDecisionSnapshot>;
  ocr?: Partial<BotCockpitOcrSnapshot>;
  operator?: Partial<BotCockpitOperatorSnapshot>;
  signals?: BotCockpitSignal[];
  warnings?: BotCockpitWarning[];
  transport?: Partial<BotCockpitTransportMeta>;
  refreshedAt?: string;
  notes?: string[];
  raw?: unknown;
}

export interface BotCockpitLoadOptions {
  timeoutMs?: number;
  endpoint?: string;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
}

export interface BotCockpitOperatorControlPatch {
  paused?: boolean;
  shadowModeEnabled?: boolean;
  manualOverrideEnabled?: boolean;
  autoRefreshEnabled?: boolean;
}

export interface BotCockpitHistoryLoadOptions extends BotCockpitLoadOptions {
  source?: string;
}

interface BotCockpitWirePayload {
  state?: string;
  status?: string;
  source?: string;
  message?: string;
  runtime?: UnknownRecord;
  samples?: UnknownRecord;
  spot?: UnknownRecord;
  current_spot?: UnknownRecord;
  decision?: UnknownRecord;
  current_decision?: UnknownRecord;
  ocr?: UnknownRecord;
  operator?: UnknownRecord;
  notes?: unknown[];
  payload?: UnknownRecord;
  signals?: unknown[];
  warnings?: unknown[];
  refreshed_at?: string;
  refreshedAt?: string;
  transport?: UnknownRecord;
  tracker?: UnknownRecord;
  gate?: UnknownRecord;
}

interface BotCockpitRuntimeWire {
  app_name?: string;
  service?: string;
  version?: string;
  runtime?: string;
  dev_mode?: boolean;
  http_fallback_enabled?: boolean;
  healthy?: boolean;
  status?: string;
  uptime_ms?: number;
  llm?: UnknownRecord;
  metrics?: UnknownRecord;
  samples?: UnknownRecord;
}

let cachedBotCockpitPayload: BotCockpitPayload | null = null;

function asRecord(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : {};
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizeRuntimeEventHistory(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((entry) => {
      if (typeof entry === "string") {
        return entry;
      }

      const raw = asRecord(entry);
      const kind = asString(raw.kind);
      const message = asString(raw.message);
      if (message.length === 0) {
        return "";
      }
      return kind.length > 0 ? `${kind}: ${message}` : message;
    })
    .filter((entry) => entry.length > 0);
}

function dedupeWarnings(values: string[]): BotCockpitWarning[] {
  return values.filter(
    (warning, index, array): warning is BotCockpitWarning =>
      warning.trim().length > 0 && array.indexOf(warning) === index
  );
}

function normalizeState(value: unknown): BotCockpitState | null {
  const state = asString(value);
  if (state === "live" || state === "degraded" || state === "offline" || state === "error") {
    return state;
  }
  return null;
}

function normalizeLlmSnapshot(value: unknown): BotCockpitLlmSnapshot {
  const raw = asRecord(value);
  return {
    enabled: asBoolean(raw.enabled),
    providerMode: asString(raw.provider_mode ?? raw.providerMode, "disabled"),
    baseUrl: asString(raw.base_url ?? raw.baseUrl),
    model: asString(raw.model),
    privacyMode: asString(raw.privacy_mode ?? raw.privacyMode, "strict_local"),
  };
}

function normalizeRuntimeMetrics(value: unknown): BotCockpitRuntimeMetrics {
  const raw = asRecord(value);
  return {
    decisionCount: asNumber(raw.decision_count ?? raw.decisionCount),
    blockedCount: asNumber(raw.blocked_count ?? raw.blockedCount),
    fallbackCount: asNumber(raw.fallback_count ?? raw.fallbackCount),
    blockRate: asNumber(raw.block_rate ?? raw.blockRate),
    fallbackRate: asNumber(raw.fallback_rate ?? raw.fallbackRate),
    rollingLatencyMs: asNumber(raw.rolling_latency_ms ?? raw.rollingLatencyMs),
    decisionRate: asNumber(raw.decision_rate ?? raw.decisionRate),
    windowSize: asNumber(raw.window_size ?? raw.windowSize),
  };
}

function normalizeRuntimeSnapshot(value: unknown, source: BotCockpitSource): BotCockpitRuntimeSnapshot {
  const raw = asRecord(value) as BotCockpitRuntimeWire;
  return {
    appName: asString(raw.app_name, asString(raw.service, "PokerMaster")),
    version: asString(raw.version, "v2"),
    runtime: asString(raw.runtime, source === "tauri" ? "tauri" : "local_rest"),
    devMode: asBoolean(raw.dev_mode),
    httpFallbackEnabled: asBoolean(raw.http_fallback_enabled, true),
    healthy: asBoolean(raw.healthy, asString(raw.status, "ok") === "ok"),
    status: asString(raw.status, "ok"),
    uptimeMs: asNumber(raw.uptime_ms),
    llm: normalizeLlmSnapshot(raw.llm ?? asRecord(raw.samples).llm_config),
    metrics: normalizeRuntimeMetrics(raw.metrics),
  };
}

function normalizeLegalActions(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return asStringArray(value);
  }

  return value
    .map((entry) => {
      if (typeof entry === "string") {
        return entry;
      }
      const raw = asRecord(entry);
      return asString(raw.label ?? raw.name);
    })
    .filter((entry) => entry.trim().length > 0);
}

function inferNumPlayers(raw: UnknownRecord, villainRanges: unknown): number {
  const explicit = asNumber(raw.num_players ?? raw.numPlayers, 0);
  if (explicit > 0) {
    return explicit;
  }

  const positions = asRecord(raw.positions);
  const playerCount = asNumber(positions.players, 0);
  if (playerCount > 0) {
    return playerCount + 1;
  }

  const villainCount = asStringArray(villainRanges).length;
  return Math.max(2, villainCount + 1);
}

function inferStreet(board: string[]): BotCockpitSpotSnapshot["street"] {
  if (board.length >= 5) {
    return "river";
  }
  if (board.length === 4) {
    return "turn";
  }
  if (board.length >= 3) {
    return "flop";
  }
  return "preflop";
}

function normalizeSpotSnapshot(value: unknown): BotCockpitSpotSnapshot {
  const raw = asRecord(value);
  const board = asStringArray(raw.board ?? raw.board_cards ?? raw.community_cards);
  const heroCards = asStringArray(raw.hero_cards ?? raw.heroCards ?? raw.hero_hand);
  const metadata = asRecord(raw.metadata);
  const persistedActionHistory = asStringArray(
    raw.action_history ?? raw.actionHistory ?? metadata.action_history
  );
  const runtimeEventHistory = normalizeRuntimeEventHistory(metadata.runtime_event_history);
  const legalActions = normalizeLegalActions(raw.legal_actions ?? raw.legalActions);
  const heroRange = asString(raw.hero_range ?? raw.heroRange);
  const villainRanges = asStringArray(raw.villain_ranges ?? raw.villainRanges);
  const ocrMetadata = asRecord(raw.ocr_metadata ?? raw.ocrMetadata);
  const rawRanges = raw.ranges;
  const ranges =
    Array.isArray(rawRanges)
      ? {
          hero: rawRanges[0] ?? "",
          villains: rawRanges.slice(1),
        }
      : Object.keys(asRecord(rawRanges)).length > 0
        ? asRecord(rawRanges)
        : {
            hero: heroRange,
            villains: villainRanges,
          };

  return {
    street: inferStreet(board),
    heroPosition: asString(raw.hero_position ?? raw.heroPosition, "") || null,
    heroSeatId: asString(raw.hero_seat_id ?? raw.heroSeatId ?? metadata.hero_seat_id, "") || null,
    pot: asNumber(raw.pot),
    effectiveStack: asNumber(raw.effective_stack ?? raw.effectiveStack ?? raw.stack),
    numPlayers: inferNumPlayers(raw, villainRanges),
    board,
    heroCards,
    actionHistory: persistedActionHistory,
    legalActions,
    ranges,
    source: asString(raw.source, "runtime"),
    metadata: {
      ...metadata,
      action_history: persistedActionHistory,
      runtime_event_history: runtimeEventHistory,
    },
    ocrMetadata,
  };
}

function normalizeDecisionAlternative(value: unknown, chosenAction: string): BotCockpitDecisionAlternative {
  const raw = asRecord(value);
  const name = asString(raw.name ?? raw.action ?? raw.raw_action);
  return {
    name,
    size: asNullableNumber(raw.size),
    frequency: asNumber(raw.frequency ?? raw.freq),
    ev: asNumber(raw.ev ?? raw.hero_ev),
    isRecommended:
      asBoolean(raw.is_recommended) ||
      asBoolean(raw.isRecommended) ||
      (name.length > 0 && name === chosenAction),
  };
}

function normalizeDecisionSnapshot(value: unknown): BotCockpitDecisionSnapshot {
  const raw = asRecord(value);
  const gateResult = asRecord(raw.gate_result ?? raw.gateResult);
  const metadata = asRecord(raw.metadata);
  const chosenAction = asString(raw.chosen_action ?? raw.chosenAction ?? raw.action);
  const decisionTraceHistory = Array.isArray(metadata.decision_trace_history) ? metadata.decision_trace_history : [];
  const runtimeEventHistory = Array.isArray(metadata.runtime_event_history) ? metadata.runtime_event_history : [];
  const incidentLog = Array.isArray(metadata.incident_log) ? metadata.incident_log : [];
  const warningHistory = [
    ...asStringArray(metadata.warning_history),
    ...runtimeEventHistory
      .map((entry) => asRecord(entry))
      .filter((entry) => asString(entry.kind) === "warning")
      .map((entry) => asString(entry.message))
      .filter((entry) => entry.length > 0),
  ];
  const fallbackHistory = [
    ...asStringArray(metadata.fallback_history),
    ...decisionTraceHistory
      .map((entry) => asRecord(entry))
      .map((entry) => asString(entry.source))
      .filter((entry) => entry === "fallback"),
  ];
  const alternativesRaw = Array.isArray(raw.alternatives)
    ? raw.alternatives
    : Array.isArray(raw.alternatives_complete)
      ? raw.alternatives_complete
    : Array.isArray(raw.actions)
      ? raw.actions
      : [];
  const alternatives = alternativesRaw.map((alternative) =>
    normalizeDecisionAlternative(alternative, chosenAction)
  );
  const heroEv = asNumber(
    raw.hero_ev ?? raw.heroEv ?? raw.ev,
    alternatives.reduce((best, alternative) => Math.max(best, alternative.ev), 0)
  );
  return {
    chosenAction,
    source: asString(raw.source, chosenAction ? "native" : "legacy"),
    alternatives,
    heroEv,
    exploitability: asNumber(raw.exploitability),
    warnings: dedupeWarnings(asStringArray(raw.warnings)),
    latencyMs: asNumber(raw.latency_ms ?? raw.latencyMs ?? raw.elapsed_ms ?? raw.elapsedMs),
    confidence: asNumber(raw.confidence ?? raw.decision_confidence ?? raw.decisionConfidence, chosenAction ? 0.55 : 0),
    gateConfidence: asNumber(
      gateResult.confidence ?? raw.gate_confidence ?? raw.gateConfidence,
      asNumber(raw.confidence ?? raw.decision_confidence, 0)
    ),
    observedHands: asNumber(raw.observed_hands ?? raw.observedHands ?? asRecord(raw.profile).observed_hands ?? metadata.observed_hands),
    metadata: {
      ...metadata,
      gate_reason: asString(gateResult.reason, asString(metadata.gate_reason, "ready")),
      gate_allowed: asBoolean(gateResult.allowed, true),
      gate_confidence: asNumber(
        gateResult.confidence,
        asNumber(
          raw.gate_confidence ?? metadata.gate_confidence,
          asNumber(raw.confidence ?? raw.decision_confidence, 0)
        )
      ),
      fallback_history: Array.from(new Set(fallbackHistory)),
      warning_history: Array.from(new Set(warningHistory)),
      observed_hands: asNumber(raw.observed_hands ?? raw.observedHands ?? asRecord(raw.profile).observed_hands ?? metadata.observed_hands),
      incidents: Array.from(
        new Set([
          ...asStringArray(metadata.incidents),
          ...incidentLog
            .map((entry) => asRecord(entry))
            .map((entry) => asString(entry.id))
            .filter((entry) => entry.length > 0),
          ...asStringArray(raw.warnings),
          ...asStringArray(gateResult.warnings),
        ])
      ),
      cache_hit: asBoolean(raw.cache_hit ?? raw.cacheHit ?? metadata.cache_hit),
      fallback_used:
        asBoolean(gateResult.metadata && asRecord(gateResult.metadata).fallback_used) ||
        asString(raw.source) === "fallback",
      decision_trace_history: decisionTraceHistory,
      runtime_event_history: runtimeEventHistory,
    },
  };
}

function normalizeOcrSnapshot(value: unknown, spot: BotCockpitSpotSnapshot): BotCockpitOcrSnapshot {
  const raw = asRecord(value);
  const metadata = asRecord(spot.ocrMetadata);
  const rawCandidates = raw.candidates ?? metadata.candidates;
  const candidates = Array.isArray(rawCandidates)
    ? rawCandidates
        .map((entry) => asRecord(entry))
        .filter((entry) => Object.keys(entry).length > 0)
    : [];
  return {
    confidence: asNumber(raw.confidence ?? metadata.selected_confidence ?? metadata.confidence),
    drift: asString(raw.drift ?? metadata.agreement, asString(metadata.agreement, "stable")),
    frameLabel: asString(raw.frame_label ?? raw.frameLabel, asString(metadata.field, "live_runtime")),
    notes: asStringArray(raw.notes ?? metadata.notes),
    source: asString(raw.source ?? metadata.selected_engine, "runtime"),
    mode: asString(raw.mode ?? metadata.mode),
    selectedEngine: asString(raw.selected_engine ?? raw.selectedEngine ?? metadata.selected_engine),
    loadedEngines: asStringArray(raw.loaded_engines ?? raw.loadedEngines ?? metadata.loaded_engines),
    requestedEngines: asStringArray(raw.requested_engines ?? raw.requestedEngines ?? metadata.requested_engines),
    agreement: asString(raw.agreement ?? metadata.agreement),
    selectedConfidence: asNumber(raw.selected_confidence ?? raw.selectedConfidence ?? metadata.selected_confidence),
    engineScores:
      typeof (raw.engine_scores ?? raw.engineScores ?? metadata.engine_scores) === "object" &&
      (raw.engine_scores ?? raw.engineScores ?? metadata.engine_scores) !== null
        ? Object.fromEntries(
            Object.entries((raw.engine_scores ?? raw.engineScores ?? metadata.engine_scores) as Record<string, unknown>)
              .filter(([, value]) => typeof value === "number" && Number.isFinite(value))
              .map(([key, value]) => [key, value as number])
          )
        : {},
    candidates,
  };
}

function normalizeOperatorSnapshot(value: unknown): BotCockpitOperatorSnapshot {
  const raw = asRecord(value);
  const status = asString(raw.status, "ready");
  return {
    profileName: asString(raw.profile_name ?? raw.profileName, "local-operator"),
    surface: asString(raw.surface, "bot_cockpit"),
    captureSource: asString(raw.capture_source ?? raw.captureSource, "runtime"),
    autoRefreshEnabled: asBoolean(raw.auto_refresh_enabled ?? raw.autoRefreshEnabled, true),
    shadowModeEnabled: asBoolean(raw.shadow_mode_enabled ?? raw.shadowModeEnabled, false),
    manualOverrideEnabled: asBoolean(raw.manual_override_enabled ?? raw.manualOverrideEnabled, false),
    paused: status === "paused" || asBoolean(raw.paused),
    status,
  };
}

function normalizeSignals(value: unknown, payload: BotCockpitPayload): BotCockpitSignal[] {
  if (Array.isArray(value)) {
    const normalized = value
      .map((entry) => asRecord(entry))
      .filter((entry) => asString(entry.label).trim().length > 0)
      .map((entry) => ({
        label: asString(entry.label),
        value: asString(entry.value, "n/a"),
        note: asString(entry.note, ""),
      }));
    if (normalized.length > 0) {
      return normalized;
    }
  }

  const metrics = payload.runtime.metrics;
  return [
    {
      label: "Runtime",
      value: payload.runtime.runtime,
      note: payload.runtime.status,
    },
    {
      label: "Mode",
      value: payload.state,
      note: payload.message,
    },
    {
      label: "OCR",
      value: `${Math.round(payload.ocr.confidence * 100)}%`,
      note: payload.ocr.drift,
    },
    {
      label: "Decision",
      value: payload.decision.chosenAction || "pending",
      note: payload.decision.source,
    },
    {
      label: "Block rate",
      value: `${Math.round(metrics.blockRate * 100)}%`,
      note: `${metrics.blockedCount}/${metrics.decisionCount || metrics.windowSize || 0}`,
    },
    {
      label: "Fallback rate",
      value: `${Math.round(metrics.fallbackRate * 100)}%`,
      note: `${metrics.fallbackCount}/${metrics.decisionCount || metrics.windowSize || 0}`,
    },
    {
      label: "Latency",
      value: `${Math.round(metrics.rollingLatencyMs)} ms`,
      note: `rolling x${metrics.windowSize || metrics.decisionCount || 0}`,
    },
    {
      label: "Decision rate",
      value: `${metrics.decisionRate.toFixed(2)}/min`,
      note: "local window",
    },
  ];
}

function buildDefaultSpotSnapshot(overrides: Partial<BotCockpitSpotSnapshot> = {}): BotCockpitSpotSnapshot {
  const board = overrides.board !== undefined ? [...overrides.board] : [];
  const heroCards = overrides.heroCards !== undefined ? [...overrides.heroCards] : [];
  const actionHistory = overrides.actionHistory !== undefined ? [...overrides.actionHistory] : [];
  const legalActions = overrides.legalActions !== undefined ? [...overrides.legalActions] : [];
  const ranges = overrides.ranges !== undefined ? { ...overrides.ranges } : {};
  const metadata = overrides.metadata !== undefined ? { ...overrides.metadata } : {};
  const ocrMetadata = overrides.ocrMetadata !== undefined ? { ...overrides.ocrMetadata } : {};

  return {
    street: overrides.street ?? "preflop",
    heroPosition: overrides.heroPosition ?? null,
    heroSeatId: overrides.heroSeatId ?? null,
    pot: overrides.pot ?? 0,
    effectiveStack: overrides.effectiveStack ?? 0,
    numPlayers: overrides.numPlayers ?? 2,
    board,
    heroCards,
    actionHistory,
    legalActions,
    ranges,
    source: overrides.source ?? "fallback",
    metadata,
    ocrMetadata,
  };
}

function buildDefaultDecisionSnapshot(overrides: Partial<BotCockpitDecisionSnapshot> = {}): BotCockpitDecisionSnapshot {
  const alternatives =
    overrides.alternatives !== undefined ? overrides.alternatives.map((alt) => ({ ...alt })) : [];
  const warnings = overrides.warnings !== undefined ? [...overrides.warnings] : [];
  const metadata = overrides.metadata !== undefined ? { ...overrides.metadata } : {};

  return {
    chosenAction: overrides.chosenAction ?? "",
    source: overrides.source ?? "fallback",
    alternatives,
    heroEv: overrides.heroEv ?? 0,
    exploitability: overrides.exploitability ?? 0,
    warnings,
    latencyMs: overrides.latencyMs ?? 0,
    confidence: overrides.confidence ?? 0,
    gateConfidence: overrides.gateConfidence ?? overrides.confidence ?? 0,
    observedHands: overrides.observedHands ?? 0,
    metadata,
  };
}

function buildDefaultOcrSnapshot(overrides: Partial<BotCockpitOcrSnapshot> = {}): BotCockpitOcrSnapshot {
  const notes = overrides.notes !== undefined ? [...overrides.notes] : [];
  const loadedEngines = overrides.loadedEngines !== undefined ? [...overrides.loadedEngines] : [];
  const requestedEngines = overrides.requestedEngines !== undefined ? [...overrides.requestedEngines] : [];
  const candidates = overrides.candidates !== undefined ? [...overrides.candidates] : [];

  return {
    confidence: overrides.confidence ?? 0.2,
    drift: overrides.drift ?? "offline",
    frameLabel: overrides.frameLabel ?? "offline fallback",
    notes,
    source: overrides.source ?? "fallback",
    mode: overrides.mode ?? "consensus_amounts",
    selectedEngine: overrides.selectedEngine ?? "",
    loadedEngines,
    requestedEngines,
    agreement: overrides.agreement ?? "none",
    selectedConfidence: overrides.selectedConfidence ?? overrides.confidence ?? 0.2,
    engineScores: overrides.engineScores ?? {},
    candidates,
  };
}

function buildDefaultOperatorSnapshot(
  overrides: Partial<BotCockpitOperatorSnapshot> = {}
): BotCockpitOperatorSnapshot {
  return {
    profileName: "local-operator",
    surface: "bot_cockpit",
    captureSource: "fallback",
    autoRefreshEnabled: true,
    shadowModeEnabled: false,
    manualOverrideEnabled: false,
    paused: false,
    status: "ready",
    ...overrides,
  };
}

function buildDefaultRuntimeSnapshot(overrides: Partial<BotCockpitRuntimeSnapshot> = {}): BotCockpitRuntimeSnapshot {
  const llm = {
    enabled: overrides.llm?.enabled ?? false,
    providerMode: overrides.llm?.providerMode ?? "disabled",
    baseUrl: overrides.llm?.baseUrl ?? "",
    model: overrides.llm?.model ?? "",
    privacyMode: overrides.llm?.privacyMode ?? "strict_local",
  };

  return {
    appName: overrides.appName ?? "PokerMaster",
    version: overrides.version ?? "v2",
    runtime: overrides.runtime ?? "browser",
    devMode: overrides.devMode ?? false,
    httpFallbackEnabled: overrides.httpFallbackEnabled ?? true,
    healthy: overrides.healthy ?? false,
    status: overrides.status ?? "offline",
    uptimeMs: overrides.uptimeMs ?? 0,
    llm,
    metrics: {
      decisionCount: overrides.metrics?.decisionCount ?? 0,
      blockedCount: overrides.metrics?.blockedCount ?? 0,
      fallbackCount: overrides.metrics?.fallbackCount ?? 0,
      blockRate: overrides.metrics?.blockRate ?? 0,
      fallbackRate: overrides.metrics?.fallbackRate ?? 0,
      rollingLatencyMs: overrides.metrics?.rollingLatencyMs ?? 0,
      decisionRate: overrides.metrics?.decisionRate ?? 0,
      windowSize: overrides.metrics?.windowSize ?? 0,
    },
  };
}

function deriveState(
  payload: Partial<BotCockpitPayload>,
  transport: BotCockpitTransportMeta
): BotCockpitState {
  const explicitState = normalizeState(payload.state);
  if (explicitState) {
    return explicitState;
  }
  if (transport.source === "fallback") {
    return "offline";
  }
  if (payload.runtime && payload.runtime.status === "ok" && payload.runtime.healthy) {
    return "live";
  }
  if (payload.runtime && payload.runtime.status === "offline") {
    return "offline";
  }
  if (transport.reachable) {
    return "degraded";
  }
  return "error";
}

function buildMessage(payload: BotCockpitPayload): string {
  if (payload.state === "live") {
    return `Bot cockpit live on ${payload.runtime.runtime}.`;
  }
  if (payload.state === "degraded") {
    return `Bot cockpit degraded on ${payload.transport.source}; runtime still available.`;
  }
  if (payload.state === "offline") {
    return "Bot cockpit offline-safe fallback is active.";
  }
  return "Bot cockpit payload could not be loaded.";
}

export function createDefaultBotCockpitPayload(
  overrides: BotCockpitPayloadOverrides = {}
): BotCockpitPayload {
  const transport: BotCockpitTransportMeta = {
    endpoint: "fallback",
    source: "fallback",
    reachable: false,
    httpStatus: null,
    ...overrides.transport,
  };

  const payload: BotCockpitPayload = {
    state: overrides.state ?? "offline",
    source: overrides.source ?? "fallback",
    message: overrides.message ?? "Bot cockpit offline-safe fallback is active.",
    runtime: buildDefaultRuntimeSnapshot(overrides.runtime),
    spot: buildDefaultSpotSnapshot(overrides.spot),
    decision: buildDefaultDecisionSnapshot(overrides.decision),
    ocr: buildDefaultOcrSnapshot(overrides.ocr),
    operator: buildDefaultOperatorSnapshot(overrides.operator),
    signals: overrides.signals ? overrides.signals.map((signal) => ({ ...signal })) : [],
    warnings: overrides.warnings ? [...overrides.warnings] : ["fallback_used"],
    transport,
    refreshedAt: overrides.refreshedAt ?? new Date().toISOString(),
    notes: overrides.notes ? [...overrides.notes] : [],
    raw: overrides.raw ?? null,
  };

  if (payload.signals.length === 0) {
    payload.signals = normalizeSignals([], payload);
  }

  if (!overrides.message) {
    payload.message = buildMessage(payload);
  }

  return payload;
}

function normalizeBotCockpitPayload(
  rawValue: unknown,
  transport: BotCockpitTransportMeta
): BotCockpitPayload {
  const root = asRecord(rawValue) as BotCockpitWirePayload;
  const raw = asRecord(root.payload ?? root) as BotCockpitWirePayload;
  const runtimeContainer = asRecord(raw.runtime ?? root);
  const trackerContainer = asRecord(raw.tracker ?? runtimeContainer.tracker);
  const gateContainer = asRecord(raw.gate ?? runtimeContainer.gate);
  const samples = asRecord(runtimeContainer.samples ?? root.samples);
  const runtime = normalizeRuntimeSnapshot(raw.runtime ?? raw, transport.source);
  const spot = normalizeSpotSnapshot(
    raw.spot ?? raw.current_spot ?? trackerContainer ?? samples.spot_snapshot ?? raw
  );
  const decision = normalizeDecisionSnapshot(
    raw.decision ?? raw.current_decision ?? runtimeContainer.decision ?? { ...raw, ...gateContainer, ...asRecord(runtimeContainer.decision) }
  );
  const ocr = normalizeOcrSnapshot(
    raw.ocr ?? spot.ocrMetadata ?? { confidence: spot.metadata.state_confidence ?? trackerContainer.state_confidence ?? asRecord(raw).state_confidence },
    spot
  );
  const operator = normalizeOperatorSnapshot(raw.operator);
  const runtimeMetrics = normalizeRuntimeMetrics(
    runtimeContainer.metrics ?? asRecord(spot.metadata).metrics ?? asRecord(decision.metadata).metrics
  );
  const warnings = dedupeWarnings([
    ...asStringArray(raw.warnings),
    ...asStringArray(root.warnings),
    ...(runtime.status === "offline"
      ? ["runtime_offline"]
      : runtime.status !== "ok"
        ? ["runtime_degraded"]
        : []),
    ...(ocr.confidence > 0 && ocr.confidence < 0.7 ? ["ocr_low_confidence"] : []),
  ]);

  const payload: BotCockpitPayload = {
    state: deriveState(
      {
        state: normalizeState(raw.state ?? raw.status) ?? undefined,
        runtime,
      },
      transport
    ),
    source: transport.source,
    message: asString(raw.message, ""),
    runtime: {
      ...runtime,
      metrics: runtime.metrics.windowSize > 0 ? runtime.metrics : runtimeMetrics,
    },
    spot,
    decision,
    ocr,
    operator,
    signals: [],
    warnings,
    transport,
    refreshedAt: asString(
      raw.refreshed_at ?? raw.refreshedAt ?? root.refreshed_at ?? root.refreshedAt,
      new Date().toISOString()
    ),
    notes: asStringArray(raw.notes ?? root.notes),
    raw: rawValue,
  };

  payload.signals = normalizeSignals(raw.signals, payload);
  if (!payload.message) {
    payload.message = buildMessage(payload);
  }

  return payload;
}

function createFetchImpl(fetchImpl?: typeof fetch): typeof fetch | null {
  if (fetchImpl) {
    return fetchImpl;
  }
  return typeof fetch === "function" ? fetch.bind(globalThis) : null;
}

function createAbortController(
  timeoutMs: number | undefined
): { controller: AbortController | null; cleanup: () => void } {
  if (typeof AbortController === "undefined" || !timeoutMs || timeoutMs <= 0) {
    return {
      controller: null,
      cleanup() {},
    };
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  return {
    controller,
    cleanup() {
      clearTimeout(timeoutId);
    },
  };
}

async function resolveTauriInvoke(): Promise<TauriInvoke | null> {
  const globalWindow = globalThis as typeof globalThis & {
    __TAURI__?: {
      core?: { invoke?: TauriInvoke };
      invoke?: TauriInvoke;
    };
  };

  if (typeof globalWindow.__TAURI__?.core?.invoke === "function") {
    return globalWindow.__TAURI__.core.invoke;
  }

  if (typeof globalWindow.__TAURI__?.invoke === "function") {
    return globalWindow.__TAURI__.invoke;
  }

  try {
    const core = await import("@tauri-apps/api/core");
    return typeof core.invoke === "function" ? core.invoke : null;
  } catch {
    return null;
  }
}

function delay(ms: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function allowBotCockpitSampleMode(): boolean {
  try {
    return typeof localStorage !== "undefined" && localStorage.getItem("pokermaster:v2:bot-cockpit-sample-mode") === "1";
  } catch {
    return false;
  }
}

async function loadPayloadFromTauriCommands(): Promise<BotCockpitPayload | null> {
  if (!allowBotCockpitSampleMode()) {
    return null;
  }
  const invoke = await resolveTauriInvoke();
  if (!invoke) {
    return null;
  }

  try {
    const raw = await invoke("bot_cockpit_default_payload");
    return normalizeBotCockpitPayload(raw, {
      endpoint: "bot_cockpit_default_payload",
      source: "tauri",
      reachable: true,
      httpStatus: null,
    });
  } catch {
    try {
      const refreshed = await invoke("bot_cockpit_refresh_stub");
      return normalizeBotCockpitPayload(
        refreshed,
        {
          endpoint: "bot_cockpit_refresh_stub",
          source: "tauri",
          reachable: true,
          httpStatus: null,
        }
      );
    } catch {
      return null;
    }
  }
}

async function loadPayloadFromLocalRest(
  options?: BotCockpitLoadOptions,
  mode: "load" | "refresh" = "load"
): Promise<BotCockpitPayload | null> {
  const fetchImpl = createFetchImpl(options?.fetchImpl);
  if (!fetchImpl) {
    return null;
  }

  const timeout = createAbortController(options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = options?.signal
    ? typeof AbortController === "undefined"
      ? options.signal
      : mergeSignals(options.signal, timeout.controller?.signal)
    : timeout.controller?.signal;

  try {
    const urls = options?.endpoint
      ? [options.endpoint]
      : mode === "refresh"
        ? LOCAL_BOT_COCKPIT_REFRESH_URLS
        : LOCAL_BOT_COCKPIT_URLS;

    for (const url of urls) {
      try {
        const response = await fetchImpl(url, {
          signal,
        });
        if (!response.ok) {
          continue;
        }
        const raw = await response.json();
        return normalizeBotCockpitPayload(raw, {
          endpoint: url,
          source: "local_rest",
          reachable: true,
          httpStatus: response.status,
        });
      } catch {
        // Try the next local runtime candidate.
      }
    }

    return null;
  } catch {
    return null;
  } finally {
    timeout.cleanup();
  }
}

function buildOperatorControlWirePatch(
  patch: BotCockpitOperatorControlPatch
): Record<string, boolean> {
  const wirePatch: Record<string, boolean> = {};
  if (typeof patch.paused === "boolean") {
    wirePatch.paused = patch.paused;
  }
  if (typeof patch.shadowModeEnabled === "boolean") {
    wirePatch.shadow_mode_enabled = patch.shadowModeEnabled;
  }
  if (typeof patch.manualOverrideEnabled === "boolean") {
    wirePatch.manual_override_enabled = patch.manualOverrideEnabled;
  }
  if (typeof patch.autoRefreshEnabled === "boolean") {
    wirePatch.auto_refresh_enabled = patch.autoRefreshEnabled;
  }
  return wirePatch;
}

export async function persistBotCockpitOperatorState(
  patch: BotCockpitOperatorControlPatch,
  options?: BotCockpitLoadOptions
): Promise<BotCockpitPayload> {
  const fetchImpl = createFetchImpl(options?.fetchImpl);
  if (!fetchImpl) {
    throw new Error("Bot cockpit operator endpoint unavailable");
  }

  const timeout = createAbortController(options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = options?.signal
    ? typeof AbortController === "undefined"
      ? options.signal
      : mergeSignals(options.signal, timeout.controller?.signal)
    : timeout.controller?.signal;
  const body = JSON.stringify(buildOperatorControlWirePatch(patch));
  let lastError: Error | null = null;

  try {
    const urls = options?.endpoint ? [options.endpoint] : LOCAL_BOT_COCKPIT_OPERATOR_URLS;

    for (const url of urls) {
      try {
        const response = await fetchImpl(url, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            accept: "application/json",
          },
          cache: "no-store",
          body,
          signal,
        });
        if (!response.ok) {
          lastError = new Error(`Bot cockpit operator update failed via ${url} (${response.status})`);
          continue;
        }
        const raw = await response.json();
        const payload = normalizeBotCockpitPayload(raw, {
          endpoint: url,
          source: "local_rest",
          reachable: true,
          httpStatus: response.status,
        });
        cachedBotCockpitPayload = payload;
        return payload;
      } catch (error) {
        lastError = error instanceof Error ? error : new Error("Bot cockpit operator update failed");
      }
    }
  } finally {
    timeout.cleanup();
  }

  throw lastError ?? new Error("Bot cockpit operator endpoint unavailable");
}

function appendHistorySource(url: string, source?: string): string {
  if (!source || source.trim().length === 0) {
    return url;
  }

  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}source=${encodeURIComponent(source)}`;
}

function normalizeRuntimeHistoryPayload(value: unknown): string[] {
  if (Array.isArray(value)) {
    return normalizeRuntimeEventHistory(value);
  }

  const raw = asRecord(value);
  return dedupeWarnings([
    ...normalizeRuntimeEventHistory(raw.history),
    ...normalizeRuntimeEventHistory(raw.runtime_history),
    ...normalizeRuntimeEventHistory(raw.events),
    ...normalizeRuntimeEventHistory(raw.runtime_event_history),
  ]);
}

export async function loadBotCockpitRuntimeHistory(
  options?: BotCockpitHistoryLoadOptions
): Promise<string[]> {
  const fetchImpl = createFetchImpl(options?.fetchImpl);
  if (!fetchImpl) {
    return [];
  }

  const timeout = createAbortController(options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = options?.signal
    ? typeof AbortController === "undefined"
      ? options.signal
      : mergeSignals(options.signal, timeout.controller?.signal)
    : timeout.controller?.signal;

  try {
    const urls = options?.endpoint ? [options.endpoint] : LOCAL_BOT_COCKPIT_HISTORY_URLS;

    for (const url of urls) {
      try {
        const response = await fetchImpl(appendHistorySource(url, options?.source), {
          signal,
        });
        if (!response.ok) {
          continue;
        }

        const raw = await response.json();
        const history = normalizeRuntimeHistoryPayload(raw);
        if (history.length > 0) {
          return history;
        }
      } catch {
        // Try the next local runtime candidate.
      }
    }

    return [];
  } finally {
    timeout.cleanup();
  }
}

function mergeSignals(primary?: AbortSignal, secondary?: AbortSignal): AbortSignal | undefined {
  if (!primary) {
    return secondary;
  }
  if (!secondary) {
    return primary;
  }
  if (typeof AbortController === "undefined") {
    return primary;
  }

  const merged = new AbortController();
  const abort = () => merged.abort();
  primary.addEventListener("abort", abort, { once: true });
  secondary.addEventListener("abort", abort, { once: true });
  return merged.signal;
}

function createOfflineFallback(reason = "Bot cockpit runtime unavailable"): BotCockpitPayload {
  return createDefaultBotCockpitPayload({
    state: "offline",
    source: "fallback",
    message: reason,
    transport: {
      endpoint: "fallback",
      source: "fallback",
      reachable: false,
      httpStatus: null,
    },
    warnings: ["host_unavailable", "fallback_used"],
    signals: [
      {
        label: "Runtime",
        value: "offline",
        note: reason,
      },
      {
        label: "Fallback",
        value: "enabled",
        note: "Deterministic local payload only.",
      },
    ],
  });
}

async function loadBotCockpitPayloadInternal(
  options?: BotCockpitLoadOptions,
  mode: "load" | "refresh" = "load"
): Promise<BotCockpitPayload> {
  const invoke = await resolveTauriInvoke();
  const retryDelays = options?.endpoint ? [0] : invoke ? DESKTOP_RUNTIME_RETRY_DELAYS_MS : [0];

  for (const retryDelay of retryDelays) {
    if (retryDelay > 0) {
      await delay(retryDelay);
    }
    const restPayload = await loadPayloadFromLocalRest(options, mode);
    if (restPayload) {
      cachedBotCockpitPayload = restPayload;
      return restPayload;
    }
  }

  const tauriPayload = await loadPayloadFromTauriCommands();
  if (tauriPayload) {
    cachedBotCockpitPayload = tauriPayload;
    return tauriPayload;
  }

  const fallback = createOfflineFallback();
  cachedBotCockpitPayload = fallback;
  return fallback;
}

export async function loadBotCockpitPayload(
  options?: BotCockpitLoadOptions
): Promise<BotCockpitPayload> {
  if (
    cachedBotCockpitPayload &&
    !(cachedBotCockpitPayload.source === "fallback" && !cachedBotCockpitPayload.transport.reachable)
  ) {
    return cachedBotCockpitPayload;
  }
  return loadBotCockpitPayloadInternal(options, "load");
}

export async function refreshBotCockpitPayload(
  options?: BotCockpitLoadOptions
): Promise<BotCockpitPayload> {
  return loadBotCockpitPayloadInternal(options, "refresh");
}
