export type ReplayAnalyticsSource = "tauri" | "runtime" | "offline" | "error";

export type ReplayAnalyticsStatus = "ready" | "degraded" | "offline" | "error";

export type ReplayAnalyticsRefreshMode = "load" | "refresh";

export interface ReplayAnalyticsRuntimeSnapshot {
  connected: boolean;
  transport: string;
  endpoint: string;
  refreshedAt: string;
  raw?: Record<string, unknown>;
}

export interface ReplayAnalyticsSummary {
  totalSessions: number;
  totalHands: number;
  analyzedHands: number;
  totalWinningsBb: number;
  evBbPer100: number;
  winRateBbPer100: number;
  p95LatencyMs: number;
  fallbackRate: number;
}

export interface ReplayAnalyticsHighlight {
  id: string;
  title: string;
  street: string;
  result: string;
  confidence: number;
  tags: string[];
  note: string;
}

export interface ReplayAnalyticsFilterState {
  room: string;
  hero: string;
  dateRange: string;
  presetIds: string[];
  tags: string[];
}

export interface ReplayAnalyticsPayload {
  kind: "replay_analytics";
  status: ReplayAnalyticsStatus;
  source: ReplayAnalyticsSource;
  refreshedAt: string;
  runtime: ReplayAnalyticsRuntimeSnapshot;
  summary: ReplayAnalyticsSummary;
  highlights: ReplayAnalyticsHighlight[];
  filters: ReplayAnalyticsFilterState;
  warnings: string[];
  recommendations: string[];
  notes: string[];
  raw?: Record<string, unknown>;
}

type JsonRecord = Record<string, unknown>;

const DEFAULT_REPLAY_ANALYTICS_PAYLOAD: ReplayAnalyticsPayload = {
  kind: "replay_analytics",
  status: "offline",
  source: "offline",
  refreshedAt: "2026-04-11T00:00:00.000Z",
  runtime: {
    connected: false,
    transport: "offline",
    endpoint: "",
    refreshedAt: "2026-04-11T00:00:00.000Z",
  },
  summary: {
    totalSessions: 12,
    totalHands: 3840,
    analyzedHands: 2976,
    totalWinningsBb: 186.4,
    evBbPer100: 4.7,
    winRateBbPer100: 3.1,
    p95LatencyMs: 28,
    fallbackRate: 0.08,
  },
  highlights: [
    {
      id: "rh-001",
      title: "Turn probe value line",
      street: "turn",
      result: "+6.2 bb",
      confidence: 0.91,
      tags: ["value", "probe", "turn"],
      note: "High-confidence node with stable sizing across runs.",
    },
    {
      id: "rh-002",
      title: "River bluff-catch review",
      street: "river",
      result: "-1.4 bb",
      confidence: 0.77,
      tags: ["river", "bluff-catch"],
      note: "Good candidate for re-study because the line deviates from the solver preset.",
    },
    {
      id: "rh-003",
      title: "Flop c-bet texture cluster",
      street: "flop",
      result: "+3.8 bb",
      confidence: 0.84,
      tags: ["flop", "c-bet", "cluster"],
      note: "Consistent gain across the current offline replay set.",
    },
  ],
  filters: {
    room: "all",
    hero: "all",
    dateRange: "last_30_days",
    presetIds: ["srp_hu_100bb", "3bp_hu_100bb"],
    tags: ["review", "high-ev", "spot-check"],
  },
  warnings: [
    "Offline fallback payload in use.",
    "No live analytics endpoint was available during load.",
  ],
  recommendations: [
    "Review the river bluff-catch cluster first.",
    "Re-run the turn probe spot with a tighter preset.",
    "Compare current replay summaries against the last captured solver snapshot.",
  ],
  notes: [
    "This payload is deterministic so the UI can render without a running backend.",
  ],
};

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asStringArray(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value)) {
    return fallback;
  }
  const items = value.filter(
    (entry): entry is string => typeof entry === "string" && entry.trim().length > 0
  );
  return items.length > 0 ? items : fallback;
}

function getReplayAnalyticsRecord(raw: unknown): JsonRecord {
  if (!isRecord(raw)) {
    return {};
  }

  const candidates = [
    raw,
    isRecord(raw.replay_analytics) ? raw.replay_analytics : null,
    isRecord(raw.replayAnalytics) ? raw.replayAnalytics : null,
    isRecord(raw.replay) ? raw.replay : null,
    isRecord(raw.bundle) ? raw.bundle : null,
    isRecord(raw.payload) ? raw.payload : null,
  ].filter((value): value is JsonRecord => Boolean(value));

  return candidates.find((value) =>
    Array.isArray(value.timeline) ||
    Array.isArray(value.spots) ||
    Array.isArray(value.highlights) ||
    Array.isArray(value.sessions) ||
    isRecord(value.summary) ||
    isRecord(value.summary_metrics)
  ) ?? candidates[0] ?? {};
}

function unwrapEnvelope<T>(value: unknown): T | null {
  if (!isRecord(value)) {
    return value as T | null;
  }

  if ("payload" in value && value.payload != null) {
    return value.payload as T;
  }

  if ("data" in value && value.data != null) {
    return value.data as T;
  }

  if ("result" in value && value.result != null) {
    return value.result as T;
  }

  if ("response" in value && value.response != null) {
    return value.response as T;
  }

  return value as T;
}

function getNowIso(): string {
  return new Date().toISOString();
}

function mergeReplayAnalyticsPayload(raw: unknown, defaults: ReplayAnalyticsPayload): ReplayAnalyticsPayload {
  const sourceRecord = getReplayAnalyticsRecord(raw);
  if (!isRecord(sourceRecord) || Object.keys(sourceRecord).length === 0) {
    return defaults;
  }

  const samples = isRecord(sourceRecord.samples) ? sourceRecord.samples : undefined;
  const replaySample = samples && isRecord(samples.replay_analytics) ? samples.replay_analytics : undefined;
  const summaryMetrics = isRecord(sourceRecord.summary_metrics) ? sourceRecord.summary_metrics : undefined;
  const summary =
    isRecord(sourceRecord.summary)
      ? sourceRecord.summary
      : sourceRecord.analytics && isRecord(sourceRecord.analytics)
        ? sourceRecord.analytics
        : replaySample;
  const runtime =
    isRecord(sourceRecord.runtime)
      ? sourceRecord.runtime
      : sourceRecord.runtimeSnapshot && isRecord(sourceRecord.runtimeSnapshot)
        ? sourceRecord.runtimeSnapshot
        : undefined;
  const highlights =
    Array.isArray(sourceRecord.highlights)
      ? sourceRecord.highlights
      : Array.isArray(sourceRecord.spots)
        ? sourceRecord.spots
        : Array.isArray(sourceRecord.leak_clusters)
          ? sourceRecord.leak_clusters
          : Array.isArray(replaySample?.timeline)
            ? replaySample.timeline
            : defaults.highlights;
  const filters = isRecord(sourceRecord.filters) ? sourceRecord.filters : defaults.filters;
  const sessions = Array.isArray(sourceRecord.sessions) ? sourceRecord.sessions : [];
  const normalizedTotalSessions =
    sessions.length > 0
      ? sessions.length
      : asNumber(summary?.totalSessions ?? summary?.sessions, defaults.summary.totalSessions);
  const normalizedTotalHands = asNumber(
    summary?.totalHands ??
      summary?.hands ??
      summary?.hands_indexed ??
      summaryMetrics?.hands_reviewed,
    defaults.summary.totalHands
  );
  const normalizedAnalyzedHands = asNumber(
    summary?.analyzedHands ??
      summary?.reviewedHands ??
      summary?.saved_spots ??
      summaryMetrics?.hands_reviewed,
    defaults.summary.analyzedHands
  );
  const normalizedWinnings = asNumber(
    summary?.totalWinningsBb ??
      summary?.winningsBb ??
      summaryMetrics?.net_bb ??
      summary?.best_hour_bb,
    defaults.summary.totalWinningsBb
  );
  const normalizedEv = asNumber(
    summary?.evBbPer100 ??
      summary?.ev ??
      summaryMetrics?.ev_bb ??
      summary?.session_trend_bb,
    defaults.summary.evBbPer100
  );
  const normalizedWinRate = asNumber(
    summary?.winRateBbPer100 ??
      summary?.winrate ??
      summary?.best_hour_bb,
    defaults.summary.winRateBbPer100
  );
  const normalizedLatency = asNumber(
    summary?.p95LatencyMs ??
      summary?.latencyP95Ms ??
      summaryMetrics?.p95_latency_ms,
    defaults.summary.p95LatencyMs
  );
  const normalizedFallbackRate = asNumber(
    summary?.fallbackRate ??
      summary?.fallbackRatio ??
      summaryMetrics?.fallback_rate,
    defaults.summary.fallbackRate
  );

  return {
    kind: "replay_analytics",
    status: (asString(sourceRecord.status, defaults.status) as ReplayAnalyticsStatus) ?? defaults.status,
    source: (asString(sourceRecord.source, defaults.source) as ReplayAnalyticsSource) ?? defaults.source,
    refreshedAt: asString(sourceRecord.refreshedAt, defaults.refreshedAt),
    runtime: {
      connected: typeof runtime?.connected === "boolean" ? runtime.connected : defaults.runtime.connected,
      transport: asString(runtime?.transport, defaults.runtime.transport),
      endpoint: asString(runtime?.endpoint, defaults.runtime.endpoint),
      refreshedAt: asString(runtime?.refreshedAt, defaults.runtime.refreshedAt),
      raw: isRecord(runtime) ? runtime : defaults.runtime.raw,
    },
    summary: {
      totalSessions: normalizedTotalSessions,
      totalHands: normalizedTotalHands,
      analyzedHands: normalizedAnalyzedHands,
      totalWinningsBb: normalizedWinnings,
      evBbPer100: normalizedEv,
      winRateBbPer100: normalizedWinRate,
      p95LatencyMs: normalizedLatency,
      fallbackRate: normalizedFallbackRate,
    },
    highlights: Array.isArray(highlights)
      ? highlights
          .map((item, index) => {
            if (typeof item === "string" && item.trim()) {
              return {
                id: `replay-${index + 1}`,
                title: item,
                street: "unknown",
                result: "n/a",
                confidence: 0.5,
                tags: [],
                note: item,
              } satisfies ReplayAnalyticsHighlight;
            }
            if (!isRecord(item)) {
              return null;
            }
            return {
              id: asString(item.id, `replay-${index + 1}`),
              title: asString(item.title ?? item.label, `Replay ${index + 1}`),
              street: asString(item.street, "unknown"),
              result: asString(
                item.result ??
                  item.delta ??
                  (typeof item.result_bb === "number" ? `${item.result_bb.toFixed(1)} bb` : undefined),
                "n/a"
              ),
              confidence: asNumber(item.confidence, typeof item.hands === "number" ? Math.min(item.hands / 10, 1) : 0.5),
              tags: asStringArray(item.tags, item.id ? [asString(item.id, "")].filter(Boolean) : []),
              note: asString(item.note ?? item.description ?? item.recommended_focus, ""),
            } satisfies ReplayAnalyticsHighlight;
          })
          .filter((value): value is ReplayAnalyticsHighlight => value !== null)
      : defaults.highlights,
    filters: {
      room: asString(filters?.room, defaults.filters.room),
      hero: asString(filters?.hero, defaults.filters.hero),
      dateRange: asString(filters?.dateRange, defaults.filters.dateRange),
      presetIds: asStringArray(filters?.presetIds, defaults.filters.presetIds),
      tags: asStringArray(filters?.tags, defaults.filters.tags),
    },
    warnings: asStringArray(sourceRecord.warnings, defaults.warnings),
    recommendations: asStringArray(sourceRecord.recommendations, defaults.recommendations),
    notes: asStringArray(sourceRecord.notes, defaults.notes),
    raw: isRecord(raw) ? raw : undefined,
  };
}

async function resolveTauriInvoke(): Promise<((command: string, args?: Record<string, unknown>) => Promise<unknown>) | null> {
  const globalWindow = globalThis as typeof globalThis & {
    __TAURI__?: {
      core?: { invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown> };
      invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
    };
  };

  if (typeof globalWindow.__TAURI__?.core?.invoke === "function") {
    return globalWindow.__TAURI__!.core!.invoke!;
  }

  if (typeof globalWindow.__TAURI__?.invoke === "function") {
    return globalWindow.__TAURI__!.invoke!;
  }

  try {
    const core = await import("@tauri-apps/api/core");
    if (typeof core.invoke === "function") {
      return core.invoke;
    }
  } catch {
    // Ignore: browser-only or package not installed.
  }

  return null;
}

async function tryInvokePayload<T>(commands: string[], args?: Record<string, unknown>): Promise<T | null> {
  const invoke = await resolveTauriInvoke();
  if (!invoke) {
    return null;
  }

  for (const command of commands) {
    try {
      return unwrapEnvelope<T>(await invoke(command, args));
    } catch {
      // Try the next command name.
    }
  }

  return null;
}

async function tryFetchPayload<T>(urls: string[]): Promise<T | null> {
  for (const url of urls) {
    try {
      const controller = new AbortController();
      const timeout = globalThis.setTimeout(() => controller.abort(), 2500);
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
      globalThis.clearTimeout(timeout);
      if (!response.ok) {
        continue;
      }
      return unwrapEnvelope<T>(await response.json());
    } catch {
      // Try the next URL.
    }
  }

  return null;
}

function createRuntimeSnapshot(source: ReplayAnalyticsSource, transport: string, endpoint: string, raw?: Record<string, unknown>): ReplayAnalyticsRuntimeSnapshot {
  return {
    connected: source !== "offline" && source !== "error",
    transport,
    endpoint,
    refreshedAt: getNowIso(),
    raw,
  };
}

export function createDefaultReplayAnalyticsPayload(): ReplayAnalyticsPayload {
  return {
    ...DEFAULT_REPLAY_ANALYTICS_PAYLOAD,
    refreshedAt: getNowIso(),
    runtime: {
      ...DEFAULT_REPLAY_ANALYTICS_PAYLOAD.runtime,
      refreshedAt: getNowIso(),
    },
  };
}

export function hydrateReplayAnalyticsPayloadFromBundle(raw: unknown): ReplayAnalyticsPayload {
  const defaults = createDefaultReplayAnalyticsPayload();
  return mergeReplayAnalyticsPayload(raw, {
    ...defaults,
    status: "ready",
    source: "offline",
    runtime: createRuntimeSnapshot("offline", "file", "local-json-import"),
    warnings: [
      "Loaded replay analytics from a local JSON bundle.",
      ...defaults.warnings,
    ],
    notes: [
      "Imported from a local replay bundle.",
      ...defaults.notes,
    ],
  });
}

async function loadReplayAnalyticsPayloadInternal(mode: ReplayAnalyticsRefreshMode): Promise<ReplayAnalyticsPayload> {
  const tauriCommands =
    mode === "refresh"
      ? ["replay_analytics_refresh_stub", "replay_analytics_default_payload"]
      : ["replay_analytics_default_payload", "replay_analytics_refresh_stub"];
  const restUrls =
    mode === "refresh"
      ? [
          "/replay-analytics/refresh",
          "http://127.0.0.1:8005/replay-analytics/refresh",
          "/replay-analytics/payload",
          "http://127.0.0.1:8005/replay-analytics/payload",
          "/runtime-snapshot",
          "http://127.0.0.1:8005/runtime-snapshot",
        ]
      : [
          "/replay-analytics/payload",
          "http://127.0.0.1:8005/replay-analytics/payload",
          "/runtime-snapshot",
          "http://127.0.0.1:8005/runtime-snapshot",
        ];

  const tauriPayload = await tryInvokePayload<unknown>(tauriCommands);
  if (tauriPayload) {
    const defaults = createDefaultReplayAnalyticsPayload();
    return mergeReplayAnalyticsPayload(tauriPayload, {
      ...defaults,
      status: "ready",
      source: "tauri",
      runtime: createRuntimeSnapshot("tauri", "tauri", tauriCommands[0]),
      warnings: defaults.warnings,
    });
  }

  const restPayload = await tryFetchPayload<unknown>(restUrls);
  if (restPayload) {
    const defaults = createDefaultReplayAnalyticsPayload();
    return mergeReplayAnalyticsPayload(restPayload, {
      ...defaults,
      status: "degraded",
      source: "runtime",
      runtime: createRuntimeSnapshot("runtime", "rest", restUrls[0]),
      warnings: [
        "Loaded replay analytics from a local runtime snapshot.",
        ...defaults.warnings,
      ],
    });
  }

  return createDefaultReplayAnalyticsPayload();
}

export async function loadReplayAnalyticsPayload(): Promise<ReplayAnalyticsPayload> {
  return loadReplayAnalyticsPayloadInternal("load");
}

export async function refreshReplayAnalyticsPayload(): Promise<ReplayAnalyticsPayload> {
  return loadReplayAnalyticsPayloadInternal("refresh");
}
