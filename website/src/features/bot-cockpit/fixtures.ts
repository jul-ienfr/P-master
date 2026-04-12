import type {
  BotCockpitPayload,
  BotCockpitRuntimeSnapshot,
} from "./types";

const DEFAULT_LAST_UPDATED_AT = "2026-04-11T09:00:00.000Z";
const DEFAULT_LAST_CHECKED_AT = "2026-04-11T09:00:01.000Z";

function cloneCard(card: BotCockpitRuntimeSnapshot["spot"]["heroCards"][number]) {
  return { ...card };
}

function cloneRuntime(runtime: BotCockpitRuntimeSnapshot): BotCockpitRuntimeSnapshot {
  return {
    ...runtime,
    spot: {
      ...runtime.spot,
      heroCards: runtime.spot.heroCards.map(cloneCard),
      board: runtime.spot.board.map(cloneCard),
      villainRanges: [...runtime.spot.villainRanges],
      legalActions: [...runtime.spot.legalActions],
      actionHistory: [...runtime.spot.actionHistory],
      notes: [...runtime.spot.notes],
      ranges: { ...runtime.spot.ranges },
      ocr: { ...runtime.spot.ocr },
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

function createBaseRuntime(): BotCockpitRuntimeSnapshot {
  return {
    status: "ready",
    source: "tauri",
    operatorMode: "assist",
    surface: "bot_cockpit",
    spot: {
      id: "bot-cockpit-ready-srp",
      label: "Bot cockpit ready spot",
      street: "flop",
      heroPosition: "btn",
      heroCards: [
        { rank: "A", suit: "s", label: "As" },
        { rank: "K", suit: "s", label: "Ks" },
      ],
      board: [
        { rank: "Q", suit: "s", label: "Qs" },
        { rank: "J", suit: "d", label: "Jd" },
        { rank: "4", suit: "c", label: "4c" },
      ],
      heroRange: "JJ+,AKs,AQs,AJs,KQs,AKo",
      villainRanges: ["22+,A2s+,K9s+,QTs+,JTs,T9s,98s,AJo+,KQo"],
      legalActions: ["check", "bet_50", "bet_100"],
      actionHistory: ["BTN opens 2.5x", "BB calls"],
      pot: 5.5,
      effectiveStack: 97.5,
      numPlayers: 2,
      source: "tauri",
      tableName: "Alpha-07",
      handId: "A7-1138",
      ranges: {
        hero: "JJ+,AKs,AQs,AJs,KQs,AKo",
        villain: "22+,A2s+,K9s+,QTs+,JTs,T9s,98s,AJo+,KQo",
      },
      ocr: {
        confidence: 0.96,
        provider: "screen-capture",
      },
      notes: ["Heads-up flop sample ready for live cockpit review."],
    },
    decision: {
      chosenAction: "bet_50",
      actions: [
        {
          name: "check",
          label: "Check",
          size: null,
          frequency: 0.34,
          ev: 1.12,
          isRecommended: false,
        },
        {
          name: "bet_50",
          label: "Bet 50%",
          size: 50,
          frequency: 0.49,
          ev: 1.31,
          isRecommended: true,
        },
        {
          name: "bet_100",
          label: "Bet 100%",
          size: 100,
          frequency: 0.17,
          ev: 1.08,
          isRecommended: false,
        },
      ],
      heroEv: 1.31,
      exploitability: 0.18,
      source: "native",
      warnings: [],
      latencyMs: 42,
      cacheHit: true,
      confidence: 0.94,
      presetId: "srp_hu_100bb",
      rationale: "A protected value-bet line keeps the action mix balanced on a dynamic flop.",
    },
    alerts: [
      {
        id: "bot-cockpit-alert-cache",
        kind: "solver",
        severity: "info",
        title: "Cache is warm",
        message: "The native runtime returned a cached line for the current flop sample.",
        createdAt: DEFAULT_LAST_UPDATED_AT,
        source: "tauri",
        dismissible: true,
        acknowledged: true,
        context: {
          cacheHit: true,
          presetId: "srp_hu_100bb",
        },
      },
    ],
    connection: {
      transport: "tauri",
      endpoint: "tauri://solver",
      reachable: true,
      httpStatus: null,
      latencyMs: 18,
      lastCheckedAt: DEFAULT_LAST_CHECKED_AT,
    },
    sampleId: "bot-cockpit-ready",
    title: "Ready runtime sample",
    description: "A healthy live snapshot with native decision data and one informational alert.",
    lastUpdatedAt: DEFAULT_LAST_UPDATED_AT,
    notes: ["Native runtime is the primary decision source."],
    metrics: {
      spotConfidence: 0.96,
      decisionConfidence: 0.94,
      cacheHit: true,
      openAlerts: 0,
    },
  };
}

function createDegradedRuntime(): BotCockpitRuntimeSnapshot {
  const runtime = createBaseRuntime();
  runtime.status = "degraded";
  runtime.operatorMode = "diagnostic";
  runtime.source = "local_rest";
  runtime.spot.id = "bot-cockpit-ocr-drift";
  runtime.spot.label = "OCR drift sample";
  runtime.spot.tableName = "Delta-22";
  runtime.spot.handId = "D22-9041";
  runtime.spot.ocr = {
    confidence: 0.61,
    provider: "screen-capture",
    drift: "board-card mismatch",
  };
  runtime.decision.source = "http";
  runtime.decision.cacheHit = false;
  runtime.decision.warnings = ["ocr_low_confidence", "fallback_used"];
  runtime.decision.latencyMs = 184;
  runtime.decision.confidence = 0.63;
  runtime.connection.transport = "local_rest";
  runtime.connection.endpoint = "http://127.0.0.1:8765/v2/solve";
  runtime.connection.latencyMs = 39;
  runtime.alerts = [
    {
      id: "bot-cockpit-alert-ocr",
      kind: "ocr",
      severity: "warning",
      title: "OCR confidence dipped",
      message: "Card recognition was still usable, but the board read needs verification.",
      createdAt: DEFAULT_LAST_UPDATED_AT,
      source: "local_rest",
      dismissible: true,
      acknowledged: false,
      context: {
        confidence: 0.61,
        threshold: 0.85,
      },
    },
    {
      id: "bot-cockpit-alert-fallback",
      kind: "fallback",
      severity: "info",
      title: "HTTP bridge answered",
      message: "The cockpit received a structured result from the local REST runtime.",
      createdAt: DEFAULT_LAST_UPDATED_AT,
      source: "http",
      dismissible: true,
      acknowledged: true,
      context: {
        source: "http",
        latencyMs: 184,
      },
    },
  ];
  runtime.sampleId = "bot-cockpit-degraded";
  runtime.title = "OCR drift runtime sample";
  runtime.description =
    "A degraded but usable snapshot that keeps the operator informed about OCR drift and bridge fallback.";
  runtime.notes = ["Use this payload to exercise warning banners and fallback UI."];
  runtime.metrics = {
    spotConfidence: 0.61,
    decisionConfidence: 0.63,
    cacheHit: false,
    openAlerts: 1,
  };
  return runtime;
}

function createOfflineRuntime(): BotCockpitRuntimeSnapshot {
  const runtime = createBaseRuntime();
  runtime.status = "offline";
  runtime.operatorMode = "observe_only";
  runtime.source = "browser_stub";
  runtime.spot.label = "Offline-safe sample";
  runtime.spot.tableName = "Fallback-01";
  runtime.spot.handId = "FB-0001";
  runtime.decision.source = "fallback";
  runtime.decision.chosenAction = "";
  runtime.decision.actions = [];
  runtime.decision.heroEv = 0;
  runtime.decision.exploitability = 0;
  runtime.decision.cacheHit = false;
  runtime.decision.latencyMs = 0;
  runtime.decision.confidence = 0;
  runtime.decision.warnings = ["fallback_used", "model_unavailable"];
  runtime.connection.transport = "offline";
  runtime.connection.endpoint = "";
  runtime.connection.reachable = false;
  runtime.connection.httpStatus = null;
  runtime.connection.latencyMs = null;
  runtime.alerts = [
    {
      id: "bot-cockpit-alert-offline",
      kind: "network",
      severity: "error",
      title: "Local runtime unavailable",
      message: "The cockpit is in offline-safe mode and cannot reach the local runtime.",
      createdAt: DEFAULT_LAST_UPDATED_AT,
      source: "browser_stub",
      dismissible: false,
      acknowledged: false,
      context: {
        fallback: "browser_stub",
      },
    },
  ];
  runtime.sampleId = "bot-cockpit-offline";
  runtime.title = "Offline-safe runtime sample";
  runtime.description =
    "A browser-safe fallback payload that keeps the cockpit responsive when no provider is reachable.";
  runtime.notes = ["Useful for exercising the UI when Tauri or the local server is absent."];
  runtime.metrics = {
    spotConfidence: 0.52,
    decisionConfidence: 0,
    cacheHit: false,
    openAlerts: 1,
  };
  return runtime;
}

export function createDefaultBotCockpitPayload(): BotCockpitPayload {
  const runtime = cloneRuntime(createBaseRuntime());
  return {
    sampleId: runtime.sampleId,
    title: runtime.title,
    description: runtime.description,
    runtime,
  };
}

export const DEFAULT_BOT_COCKPIT_PAYLOAD: BotCockpitPayload =
  createDefaultBotCockpitPayload();

export const BOT_COCKPIT_SAMPLE_PAYLOADS: BotCockpitPayload[] = [
  DEFAULT_BOT_COCKPIT_PAYLOAD,
  {
    sampleId: "bot-cockpit-degraded",
    title: "OCR drift runtime sample",
    description:
      "A degraded but usable snapshot that keeps the operator informed about OCR drift and bridge fallback.",
    runtime: cloneRuntime(createDegradedRuntime()),
  },
  {
    sampleId: "bot-cockpit-offline",
    title: "Offline-safe runtime sample",
    description:
      "A browser-safe fallback payload that keeps the cockpit responsive when no provider is reachable.",
    runtime: cloneRuntime(createOfflineRuntime()),
  },
];

