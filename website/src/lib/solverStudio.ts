const LOCAL_SOLVER_STUDIO_URLS = [
  "http://127.0.0.1:8765/v2/solve",
  "http://127.0.0.1:8005/v2/solve",
  "http://127.0.0.1:8005/solve",
];
const DEFAULT_TIMEOUT_MS = 12_000;
const TAURI_DEFAULT_PAYLOAD_COMMAND = "solver_studio_default_payload";
const TAURI_SOLVE_STUB_COMMAND = "solver_studio_solve_stub";

export type SolverStudioPresetId =
  | "srp_hu_100bb"
  | "srp_hu_texture_wet"
  | "3bp_hu_100bb"
  | "4bp_hu_100bb"
  | "turn_probe_hu"
  | "turn_delayed_cbet_hu"
  | "river_jam_low_spr"
  | "river_overbet_polar_hu"
  | (string & {});

export type SolverStudioWarning =
  | "unsupported_spot"
  | "approximate_ranges"
  | "multiway_approximation"
  | "timeout"
  | "cache_miss"
  | "fallback_used"
  | "ocr_low_confidence"
  | "model_unavailable"
  | "manual_override"
  | "unknown"
  | (string & {});

export type SolverStudioSolveStatus = "success" | "fallback" | "offline" | "error";

export interface SolverStudioAction {
  name: string;
  label: string;
  size: number | null;
  frequency: number;
  ev: number;
  isRecommended: boolean;
}

export interface SolverStudioSolveRequest {
  heroRange: string;
  villainRanges: string[];
  board: string[];
  startingPot: number;
  effectiveStack: number;
  heroPosition: string | null;
  actionHistory: string[];
  treePresetId: SolverStudioPresetId;
  rake: number;
  numPlayers: number;
  useCache: boolean;
  timeBudgetMs: number | null;
}

export interface SolverStudioSolveResponse {
  chosenAction: string;
  actions: SolverStudioAction[];
  heroEv: number;
  exploitability: number;
  cacheHit: boolean;
  elapsedMs: number;
  presetId: SolverStudioPresetId;
  warnings: SolverStudioWarning[];
  confidence: number;
  fallbackReason: string | null;
  incidents: Array<{
    id: string;
    severity: "info" | "warning" | "error";
    label: string;
  }>;
  gateDecision: {
    allowed: boolean;
    reason: string;
    confidence: number;
  };
}

export interface SolverStudioSpotPreset {
  id: string;
  title: string;
  description: string;
  request: SolverStudioSolveRequest;
}

export interface SolverStudioTransportMeta {
  endpoint: string;
  source: "http" | "tauri";
  reachable: boolean;
  httpStatus: number | null;
}

export interface SolverStudioSolveResult {
  status: SolverStudioSolveStatus;
  ok: boolean;
  message: string;
  request: SolverStudioSolveRequest;
  response: SolverStudioSolveResponse;
  recommendedAction: SolverStudioAction | null;
  warnings: SolverStudioWarning[];
  transport: SolverStudioTransportMeta;
  raw: unknown;
}

export interface SolverStudioSolveOptions {
  endpoint?: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  signal?: AbortSignal;
}

type UnknownRecord = Record<string, unknown>;

type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

type SolverStudioSolveRequestWire = {
  hero_range: string;
  villain_ranges: string[];
  board: string[];
  starting_pot: number;
  effective_stack: number;
  hero_position: string | null;
  action_history: string[];
  tree_preset_id: string;
  rake: number;
  num_players: number;
  use_cache: boolean;
  time_budget_ms: number | null;
};

type SolverStudioDefaultPayloadWire = {
  solve_request?: SolverStudioSolveRequestWire;
  solveRequest?: SolverStudioSolveRequestWire;
  notes?: string[];
};

function asRecord(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null ? (value as UnknownRecord) : {};
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
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

function dedupeWarnings(warnings: string[]): SolverStudioWarning[] {
  return warnings.filter(
    (warning, index, values): warning is SolverStudioWarning =>
      warning.trim().length > 0 && values.indexOf(warning) === index
  );
}

function normalizeRequest(rawValue: unknown): SolverStudioSolveRequest {
  const raw = asRecord(rawValue);
  return createDefaultSolverStudioRequest({
    heroRange: asString(raw.hero_range ?? raw.heroRange),
    villainRanges: asStringArray(raw.villain_ranges ?? raw.villainRanges),
    board: asStringArray(raw.board),
    startingPot: asNumber(raw.starting_pot ?? raw.startingPot),
    effectiveStack: asNumber(raw.effective_stack ?? raw.effectiveStack),
    heroPosition: asStringOrNull(raw.hero_position ?? raw.heroPosition),
    actionHistory: asStringArray(raw.action_history ?? raw.actionHistory),
    treePresetId: asString(raw.tree_preset_id ?? raw.treePresetId, "srp_hu_100bb") as SolverStudioPresetId,
    rake: asNumber(raw.rake),
    numPlayers: asNumber(raw.num_players ?? raw.numPlayers, 2),
    useCache: asBoolean(raw.use_cache ?? raw.useCache, true),
    timeBudgetMs: asNullableNumber(raw.time_budget_ms ?? raw.timeBudgetMs),
  });
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

function createDefaultResponse(
  request: SolverStudioSolveRequest
): SolverStudioSolveResponse {
  return {
    chosenAction: "",
    actions: [],
    heroEv: 0,
    exploitability: 0,
    cacheHit: false,
    elapsedMs: 0,
    presetId: request.treePresetId,
    warnings: [],
    confidence: 0,
    fallbackReason: null,
    incidents: [],
    gateDecision: {
      allowed: true,
      reason: "ready",
      confidence: 0,
    },
  };
}

function normalizeIncidentSeverity(value: unknown): "info" | "warning" | "error" {
  return value === "error" || value === "warning" ? value : "info";
}

function normalizeAction(rawValue: unknown, chosenAction: string): SolverStudioAction {
  const raw = asRecord(rawValue);
  const name = asString(raw.name);
  return {
    name,
    label: asString(raw.label, name),
    size: asNullableNumber(raw.size),
    frequency: asNumber(raw.frequency),
    ev: asNumber(raw.ev),
    isRecommended:
      asBoolean(raw.is_recommended) ||
      asBoolean(raw.isRecommended) ||
      (name.length > 0 && name === chosenAction),
  };
}

function normalizeResponse(
  rawValue: unknown,
  request: SolverStudioSolveRequest
): SolverStudioSolveResponse {
  const raw = asRecord(rawValue);
  const chosenAction = asString(raw.chosen_action ?? raw.chosenAction);
  const actionsRaw = Array.isArray(raw.actions) ? raw.actions : [];
  const actions = actionsRaw.map((action) => normalizeAction(action, chosenAction));
  const warnings = dedupeWarnings(asStringArray(raw.warnings));
  const incidentsRaw = Array.isArray(raw.incidents) ? raw.incidents : [];
  const confidence = asNumber(raw.confidence);
  const fallbackReason = asString(raw.fallback_reason ?? raw.fallbackReason) || null;

  return {
    chosenAction,
    actions,
    heroEv: asNumber(raw.hero_ev ?? raw.heroEv),
    exploitability: asNumber(raw.exploitability),
    cacheHit: asBoolean(raw.cache_hit ?? raw.cacheHit),
    elapsedMs: asNumber(raw.elapsed_ms ?? raw.elapsedMs),
    presetId:
      (asString(raw.preset_id ?? raw.presetId, request.treePresetId) as SolverStudioPresetId),
    warnings,
    confidence,
    fallbackReason,
    incidents: incidentsRaw.map((incident, index) => {
      const entry = asRecord(incident);
      const id = asString(entry.id, `incident-${index + 1}`);
      return {
        id,
        severity: normalizeIncidentSeverity(entry.severity),
        label: asString(entry.label, id.replace(/_/g, " ")),
      };
    }),
    gateDecision: {
      allowed: asBoolean(asRecord(raw.gate_decision ?? raw.gateDecision).allowed, fallbackReason === null),
      reason: asString(asRecord(raw.gate_decision ?? raw.gateDecision).reason, fallbackReason ?? "ready"),
      confidence: asNumber(asRecord(raw.gate_decision ?? raw.gateDecision).confidence, confidence),
    },
  };
}

function findRecommendedAction(response: SolverStudioSolveResponse): SolverStudioAction | null {
  return (
    response.actions.find((action) => action.isRecommended) ??
    response.actions.find((action) => action.name === response.chosenAction) ??
    null
  );
}

function isFallbackResponse(response: SolverStudioSolveResponse): boolean {
  if (response.warnings.includes("fallback_used")) {
    return true;
  }
  if (response.actions.length === 0 && response.chosenAction.length === 0) {
    return true;
  }
  return response.warnings.includes("unsupported_spot");
}

function buildStatusMessage(
  status: SolverStudioSolveStatus,
  response: SolverStudioSolveResponse,
  transport: SolverStudioTransportMeta,
  errorMessage?: string
): string {
  if (status === "success") {
    const action = response.chosenAction || "no action";
    return `Local solve completed with ${action} on ${response.presetId}.`;
  }
  if (status === "fallback") {
    const fallbackHints = response.warnings.length > 0 ? response.warnings.join(", ") : "structured fallback";
    return `Local solve returned a fallback response: ${fallbackHints}.`;
  }
  if (status === "offline") {
    return `Local solver endpoint is offline: ${errorMessage ?? "connection unavailable"}.`;
  }
  return `Local solve failed${transport.httpStatus ? ` (${transport.httpStatus})` : ""}: ${errorMessage ?? "unknown error"}.`;
}

function toWireRequest(request: SolverStudioSolveRequest): SolverStudioSolveRequestWire {
  return {
    hero_range: request.heroRange.trim(),
    villain_ranges: request.villainRanges.map((value) => value.trim()),
    board: request.board.map((value) => value.trim()),
    starting_pot: request.startingPot,
    effective_stack: request.effectiveStack,
    hero_position: request.heroPosition ? request.heroPosition.trim() : null,
    action_history: request.actionHistory.map((value) => value.trim()),
    tree_preset_id: request.treePresetId,
    rake: request.rake,
    num_players: request.numPlayers,
    use_cache: request.useCache,
    time_budget_ms: request.timeBudgetMs,
  };
}

function createFetchImpl(fetchImpl?: typeof fetch): typeof fetch | null {
  if (fetchImpl) {
    return fetchImpl;
  }
  return typeof fetch === "function" ? fetch.bind(globalThis) : null;
}

function buildSolveResult(
  status: SolverStudioSolveStatus,
  request: SolverStudioSolveRequest,
  response: SolverStudioSolveResponse,
  transport: SolverStudioTransportMeta,
  raw: unknown,
  errorMessage?: string,
  ok = true
): SolverStudioSolveResult {
  return {
    status,
    ok,
    message: buildStatusMessage(status, response, transport, errorMessage),
    request,
    response,
    recommendedAction: findRecommendedAction(response),
    warnings: response.warnings,
    transport,
    raw,
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

async function loadDefaultSpotFromTauri(): Promise<SolverStudioSpotPreset | null> {
  const invoke = await resolveTauriInvoke();
  if (!invoke) {
    return null;
  }

  try {
    const payload = await invoke(TAURI_DEFAULT_PAYLOAD_COMMAND);
    const raw = asRecord(payload) as SolverStudioDefaultPayloadWire;
    const request = normalizeRequest(raw.solve_request ?? raw.solveRequest);
    const notes = asStringArray(raw.notes);
    return {
      id: "tauri-default",
      title: "Exemple local par défaut",
      description:
        notes[0] ??
        "Exemple local chargé automatiquement au démarrage.",
      request,
    };
  } catch {
    return null;
  }
}

async function solveViaTauriStub(
  request: SolverStudioSolveRequest
): Promise<SolverStudioSolveResult | null> {
  const invoke = await resolveTauriInvoke();
  if (!invoke) {
    return null;
  }

  try {
    const payload = await invoke(TAURI_SOLVE_STUB_COMMAND, {
      request: toWireRequest(request),
    });
    const response = normalizeResponse(payload, request);
    const status: SolverStudioSolveStatus = isFallbackResponse(response) ? "fallback" : "success";
    return buildSolveResult(
      status,
      request,
      response,
      {
        endpoint: TAURI_SOLVE_STUB_COMMAND,
        source: "tauri",
        reachable: true,
        httpStatus: null,
      },
      payload
    );
  } catch {
    return null;
  }
}

export function createDefaultSolverStudioRequest(
  overrides: Partial<SolverStudioSolveRequest> = {}
): SolverStudioSolveRequest {
  return {
    heroRange: "AhAd",
    villainRanges: ["QQ+,AKs,AKo"],
    board: ["Ks", "7h", "2c"],
    startingPot: 7.5,
    effectiveStack: 97.5,
    heroPosition: "ip",
    actionHistory: [],
    treePresetId: "srp_hu_100bb",
    rake: 0,
    numPlayers: 2,
    useCache: true,
    timeBudgetMs: 1200,
    ...overrides,
  };
}

const SAMPLE_SPOTS: SolverStudioSpotPreset[] = [
  {
    id: "default",
    title: "Cas simple par défaut",
    description: "Un spot standard à deux joueurs pour lancer un calcul rapidement.",
    request: createDefaultSolverStudioRequest(),
  },
  {
    id: "turn-probe",
    title: "Turn après check au flop",
    description: "Pour travailler les décisions turn quand le flop n’a pas été misé.",
    request: createDefaultSolverStudioRequest({
      heroRange: "AsQs",
      villainRanges: ["99-66,AQs-A9s,KQs,QJs,JTs,T9s,98s,AQo"],
      board: ["Kd", "8s", "3c", "2h"],
      startingPot: 18,
      effectiveStack: 76,
      heroPosition: "oop",
      treePresetId: "turn_probe_hu",
      timeBudgetMs: 1500,
    }),
  },
  {
    id: "turn-delay",
    title: "Turn avec mise retardée",
    description: "Pour les spots où la première mise arrive turn.",
    request: createDefaultSolverStudioRequest({
      heroRange: "AcQc",
      villainRanges: ["77-JJ,A9s+,KTs+,QTs+,JTs,AJo+,KQo"],
      board: ["Qc", "7d", "2s", "4h"],
      startingPot: 15,
      effectiveStack: 82,
      heroPosition: "ip",
      treePresetId: "turn_delayed_cbet_hu",
      timeBudgetMs: 1650,
    }),
  },
  {
    id: "river-jam",
    title: "River avec peu de tapis restant",
    description: "Pour une décision river souvent centrée sur tapis ou call.",
    request: createDefaultSolverStudioRequest({
      heroRange: "QhQd",
      villainRanges: ["TT+,AQs+,AKo"],
      board: ["Jc", "7d", "4s", "2c", "2s"],
      startingPot: 42,
      effectiveStack: 28,
      heroPosition: "ip",
      treePresetId: "river_jam_low_spr",
      timeBudgetMs: 1000,
    }),
  },
  {
    id: "river-overbet",
    title: "River avec très grosse mise",
    description: "Pour les fins de coup où une grosse mise river est possible.",
    request: createDefaultSolverStudioRequest({
      heroRange: "AsKh",
      villainRanges: ["88+,ATs+,KQs,AQo+"],
      board: ["As", "Ts", "6d", "6c", "2h"],
      startingPot: 38,
      effectiveStack: 52,
      heroPosition: "oop",
      treePresetId: "river_overbet_polar_hu",
      timeBudgetMs: 1450,
    }),
  },
];

export function getSolverStudioSampleSpots(): SolverStudioSpotPreset[] {
  return SAMPLE_SPOTS.map((spot) => ({
    ...spot,
    request: {
      ...spot.request,
      villainRanges: [...spot.request.villainRanges],
      board: [...spot.request.board],
      actionHistory: [...spot.request.actionHistory],
    },
  }));
}

export async function loadDefaultSolverStudioSpot(): Promise<SolverStudioSpotPreset> {
  const tauriPreset = await loadDefaultSpotFromTauri();
  return tauriPreset ?? getSolverStudioSampleSpots()[0];
}

export async function loadSolverStudioSampleSpot(
  sampleId = "default"
): Promise<SolverStudioSpotPreset> {
  const match = getSolverStudioSampleSpots().find((spot) => spot.id === sampleId);
  return match ?? getSolverStudioSampleSpots()[0];
}

export async function loadSolverStudioDefaultSpot(): Promise<SolverStudioSpotPreset> {
  return loadDefaultSolverStudioSpot();
}

export async function solveSolverStudioSpot(
  requestInput: Partial<SolverStudioSolveRequest> = {},
  options: SolverStudioSolveOptions = {}
): Promise<SolverStudioSolveResult> {
  const request = createDefaultSolverStudioRequest(requestInput);
  const fetchImpl = createFetchImpl(options.fetchImpl);
  const endpoints =
    options.endpoint && options.endpoint.trim().length > 0
      ? [options.endpoint]
      : LOCAL_SOLVER_STUDIO_URLS;
  const transport: SolverStudioTransportMeta = {
    endpoint: endpoints[0] ?? "",
    source: "http",
    reachable: false,
    httpStatus: null,
  };

  if (!fetchImpl) {
    const tauriResult = await solveViaTauriStub(request);
    if (tauriResult) {
      return tauriResult;
    }

    const response = createDefaultResponse(request);
    response.warnings = ["fallback_used", "unknown"];
    return buildSolveResult(
      "offline",
      request,
      response,
      transport,
      null,
      "fetch is unavailable in this runtime",
      false
    );
  }

  const { controller, cleanup } = createAbortController(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  );

  try {
    let lastErrorMessage = "network error";
    for (const endpoint of endpoints) {
      transport.endpoint = endpoint;
      try {
        const response = await fetchImpl(endpoint, {
          method: "POST",
          headers: {
            "content-type": "application/json",
          },
          body: JSON.stringify(toWireRequest(request)),
          signal: mergeSignals(options.signal, controller?.signal),
        });

        transport.httpStatus = response.status;
        transport.reachable = true;

        if (!response.ok) {
          lastErrorMessage = await response.text().catch(() => response.statusText);
          continue;
        }

        const payload = (await response.json()) as unknown;
        const normalizedResponse = normalizeResponse(payload, request);
        const recommendedAction = findRecommendedAction(normalizedResponse);
        const status: SolverStudioSolveStatus = isFallbackResponse(normalizedResponse)
          ? "fallback"
          : "success";

        return {
          ...buildSolveResult(status, request, normalizedResponse, transport, payload),
          recommendedAction,
        };
      } catch (error) {
        lastErrorMessage = error instanceof Error ? error.message : "network error";
      }
    }

    const tauriResult = await solveViaTauriStub(request);
    if (tauriResult) {
      return tauriResult;
    }

    const response = createDefaultResponse(request);
    response.warnings = ["fallback_used", "unknown"];
    return buildSolveResult("offline", request, response, transport, null, lastErrorMessage, false);
  } catch (error) {
    const message = error instanceof Error ? error.message : "network error";
    const tauriResult = await solveViaTauriStub(request);
    if (tauriResult) {
      return tauriResult;
    }

    const response = createDefaultResponse(request);
    response.warnings = ["fallback_used", "unknown"];
    return buildSolveResult("offline", request, response, transport, error, message, false);
  } finally {
    cleanup();
  }
}

export async function solveDefaultSolverStudioSpot(
  options: SolverStudioSolveOptions = {}
): Promise<SolverStudioSolveResult> {
  const spot = await loadDefaultSolverStudioSpot();
  return solveSolverStudioSpot(spot.request, options);
}

export async function runSolverStudioSolve(
  requestInput: Partial<SolverStudioSolveRequest> = {},
  options: SolverStudioSolveOptions = {}
): Promise<SolverStudioSolveResult> {
  return solveSolverStudioSpot(requestInput, options);
}
