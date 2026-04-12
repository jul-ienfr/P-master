import {
  getDefaultSolverTreePresetId,
  getSolverTreePreset,
} from "./presets";
import type {
  SolveRequestV2Payload,
  SolveResponseV2Payload,
  SolverHeroPosition,
  SolverStreet,
  SolverStudioAction,
  SolverStudioDraftBuildResult,
  SolverStudioDraftIssue,
  SolverStudioResult,
  SolverStudioSpot,
  SolverStudioSpotDraft,
  SolverTreePresetId,
} from "./types";

function normalizeWhitespace(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function normalizeCardToken(value: string): string {
  const compact = value.replace(/\s+/g, "").replace(/^10/i, "T");
  if (compact.length < 2) {
    return compact;
  }

  const rank = compact.slice(0, compact.length - 1).toUpperCase();
  const suit = compact.slice(-1).toLowerCase();
  return `${rank}${suit}`;
}

function parseBoardText(boardText: string): string[] {
  return boardText
    .split(/[\s,|/]+/)
    .map((token) => normalizeCardToken(token))
    .filter((token) => token.length >= 2);
}

function parseLineList(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((item) => normalizeWhitespace(item))
    .filter(Boolean);
}

function parseVillainRanges(value: string): string[] {
  return value
    .split(/\n+/)
    .map((item) => normalizeWhitespace(item))
    .filter(Boolean);
}

function parseNumberInput(
  value: string,
  fallback: number,
  minimum = 0
): number {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(parsed, minimum);
}

function parseIntegerInput(
  value: string,
  fallback: number,
  minimum = 1
): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(parsed, minimum);
}

export function inferStreetFromBoard(board: string[]): SolverStreet {
  if (board.length >= 5) {
    return "river";
  }
  if (board.length === 4) {
    return "turn";
  }
  if (board.length === 3) {
    return "flop";
  }
  return "preflop";
}

export function createSolverStudioDraft(
  spot: SolverStudioSpot
): SolverStudioSpotDraft {
  return {
    label: spot.label,
    heroRange: spot.heroRange,
    villainRangesText: spot.villainRanges.join("\n"),
    boardText: spot.board.join(" "),
    heroPosition: spot.heroPosition ?? "",
    startingPot: spot.startingPot.toString(),
    effectiveStack: spot.effectiveStack.toString(),
    actionHistoryText: spot.actionHistory.join("\n"),
    treePresetId: spot.treePresetId,
    rake: spot.rake.toString(),
    numPlayers: spot.numPlayers.toString(),
    useCache: spot.useCache,
    timeBudgetMs: spot.timeBudgetMs?.toString() ?? "",
    notes: spot.notes,
  };
}

export function createSolverStudioSpot(
  draft: SolverStudioSpotDraft,
  fallback?: Partial<SolverStudioSpot>
): SolverStudioSpot {
  const presetId = draft.treePresetId || fallback?.treePresetId || getDefaultSolverTreePresetId();
  const preset = getSolverTreePreset(presetId);
  const board = parseBoardText(draft.boardText);
  const heroPosition =
    (draft.heroPosition || fallback?.heroPosition || preset.defaultHeroPosition) as
      | SolverHeroPosition
      | null;
  const label = normalizeWhitespace(draft.label) || fallback?.label || preset.label;

  return {
    id:
      fallback?.id ||
      label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") ||
      "solver-studio-spot",
    label,
    heroRange: normalizeWhitespace(draft.heroRange) || fallback?.heroRange || "",
    villainRanges:
      parseVillainRanges(draft.villainRangesText).length > 0
        ? parseVillainRanges(draft.villainRangesText)
        : [...(fallback?.villainRanges ?? [])],
    board: board.length > 0 ? board : [...(fallback?.board ?? preset.defaultBoard)],
    heroPosition,
    startingPot: parseNumberInput(
      draft.startingPot,
      fallback?.startingPot ?? preset.defaultStartingPot
    ),
    effectiveStack: parseNumberInput(
      draft.effectiveStack,
      fallback?.effectiveStack ?? preset.defaultEffectiveStack
    ),
    actionHistory:
      parseLineList(draft.actionHistoryText).length > 0
        ? parseLineList(draft.actionHistoryText)
        : [...(fallback?.actionHistory ?? [])],
    treePresetId: preset.id,
    rake: parseNumberInput(draft.rake, fallback?.rake ?? 0),
    numPlayers: parseIntegerInput(
      draft.numPlayers,
      fallback?.numPlayers ?? preset.recommendedNumPlayers
    ),
    useCache: draft.useCache,
    timeBudgetMs: draft.timeBudgetMs
      ? parseIntegerInput(
          draft.timeBudgetMs,
          fallback?.timeBudgetMs ?? preset.defaultTimeBudgetMs
        )
      : fallback?.timeBudgetMs ?? preset.defaultTimeBudgetMs,
    street: inferStreetFromBoard(board.length > 0 ? board : preset.defaultBoard),
    tags: Array.from(new Set([...(fallback?.tags ?? []), ...preset.tags])),
    notes: normalizeWhitespace(draft.notes),
  };
}

export function mapStudioSpotToSolveRequest(
  spot: SolverStudioSpot
): SolveRequestV2Payload {
  return {
    hero_range: spot.heroRange,
    villain_ranges: [...spot.villainRanges],
    board: [...spot.board],
    starting_pot: spot.startingPot,
    effective_stack: spot.effectiveStack,
    hero_position: spot.heroPosition,
    action_history: [...spot.actionHistory],
    tree_preset_id: spot.treePresetId,
    rake: spot.rake,
    num_players: spot.numPlayers,
    use_cache: spot.useCache,
    time_budget_ms: spot.timeBudgetMs,
  };
}

export function buildSolveRequestFromStudioSpot(
  spot: SolverStudioSpot
): SolveRequestV2Payload {
  return mapStudioSpotToSolveRequest(spot);
}

export function mapSolveRequestToStudioSpot(
  request: SolveRequestV2Payload,
  label = "Imported Solver Spot"
): SolverStudioSpot {
  const preset = getSolverTreePreset(request.tree_preset_id);
  const board = [...request.board];

  return {
    id: `${request.tree_preset_id}-${board.join("-") || "preflop"}`,
    label,
    heroRange: request.hero_range,
    villainRanges: [...request.villain_ranges],
    board,
    heroPosition: (request.hero_position as SolverHeroPosition | null) ?? null,
    startingPot: request.starting_pot,
    effectiveStack: request.effective_stack,
    actionHistory: [...request.action_history],
    treePresetId: request.tree_preset_id,
    rake: request.rake,
    numPlayers: request.num_players,
    useCache: request.use_cache,
    timeBudgetMs: request.time_budget_ms,
    street: inferStreetFromBoard(board),
    tags: [...preset.tags],
    notes: "",
  };
}

export function buildSolverStudioRequest(
  draft: SolverStudioSpotDraft,
  fallback?: Partial<SolverStudioSpot>
): SolverStudioDraftBuildResult {
  const spot = createSolverStudioSpot(draft, fallback);
  const request = mapStudioSpotToSolveRequest(spot);
  const issues: SolverStudioDraftIssue[] = [];

  if (!spot.heroRange) {
    issues.push({
      field: "heroRange",
      severity: "error",
      message: "Add your possible hands before running the calculation.",
    });
  }

  if (spot.villainRanges.length === 0) {
    issues.push({
      field: "villainRanges",
      severity: "error",
      message: "Add at least one opponent range before running the calculation.",
    });
  }

  if (![0, 3, 4, 5].includes(spot.board.length)) {
    issues.push({
      field: "board",
      severity: "warning",
      message: "The board usually contains 0, 3, 4, or 5 cards.",
    });
  }

  if (!spot.heroPosition) {
    issues.push({
      field: "heroPosition",
      severity: "error",
      message: "Choose your position before running the calculation.",
    });
  }

  if (spot.numPlayers > 2) {
    issues.push({
      field: "compatibility",
      severity: "warning",
      message: "More than two players currently uses a simplified fallback mode.",
    });
  }

  if (spot.rake > 0) {
    issues.push({
      field: "compatibility",
      severity: "info",
      message: "Non-zero rake is kept, but it currently switches the solve to fallback mode.",
    });
  }

  return { spot, request, issues };
}

function buildRequestFingerprint(request: SolveRequestV2Payload): string {
  return [
    request.tree_preset_id,
    request.hero_position ?? "unknown",
    request.board.join("-"),
    request.starting_pot.toFixed(2),
    request.effective_stack.toFixed(2),
    request.villain_ranges.length.toString(),
    request.action_history.join(">"),
  ].join("|");
}

function mapAction(action: SolveResponseV2Payload["actions"][number]): SolverStudioAction {
  return {
    id: action.name,
    name: action.name,
    label: action.label || action.name,
    size: action.size,
    frequency: action.frequency,
    ev: action.ev,
    recommended: action.is_recommended,
  };
}

function normalizeIncidentSeverity(
  value: unknown
): "info" | "warning" | "error" {
  return value === "error" || value === "warning" ? value : "info";
}

export function mapSolveResponseToStudioResult(
  response: SolveResponseV2Payload,
  request?: SolveRequestV2Payload
): SolverStudioResult {
  const actions = response.actions.map(mapAction);
  const recommendedAction =
    actions.find((action) => action.recommended || action.name === response.chosen_action) ?? null;

  return {
    chosenAction: response.chosen_action,
    recommendedAction,
    actions,
    heroEv: response.hero_ev,
    exploitability: response.exploitability,
    cacheHit: response.cache_hit,
    elapsedMs: response.elapsed_ms,
    presetId: response.preset_id,
    warnings: [...response.warnings],
    requestFingerprint: request ? buildRequestFingerprint(request) : response.preset_id,
    confidence:
      typeof response.confidence === "number" && Number.isFinite(response.confidence)
        ? response.confidence
        : 0,
    fallbackReason: response.fallback_reason ?? null,
    incidents: Array.isArray(response.incidents)
      ? response.incidents.map((incident, index) => ({
          id:
            typeof incident?.id === "string" && incident.id.trim().length > 0
              ? incident.id
              : `incident-${index + 1}`,
          severity: normalizeIncidentSeverity(incident?.severity),
          label:
            typeof incident?.label === "string" && incident.label.trim().length > 0
              ? incident.label
              : typeof incident?.id === "string"
                ? incident.id.replace(/_/g, " ")
                : `incident ${index + 1}`,
        }))
      : [],
    gateDecision: {
      allowed: response.gate_decision?.allowed !== false,
      reason: response.gate_decision?.reason ?? response.fallback_reason ?? "ready",
      confidence:
        typeof response.gate_decision?.confidence === "number" && Number.isFinite(response.gate_decision.confidence)
          ? response.gate_decision.confidence
          : typeof response.confidence === "number" && Number.isFinite(response.confidence)
            ? response.confidence
            : 0,
    },
  };
}

export function mapSolveResponseToStudioState(
  response: SolveResponseV2Payload,
  request?: SolveRequestV2Payload
): SolverStudioResult {
  return mapSolveResponseToStudioResult(response, request);
}

export function createEmptySolveResponse(
  presetId: SolverTreePresetId
): SolveResponseV2Payload {
  return {
    chosen_action: "",
    actions: [],
    hero_ev: 0,
    exploitability: 0,
    cache_hit: false,
    elapsed_ms: 0,
    preset_id: presetId,
    warnings: ["unsupported_spot"],
    confidence: 0,
    fallback_reason: "unsupported_spot",
    incidents: [
      {
        id: "unsupported_spot",
        severity: "warning",
        label: "Spot non pris en charge",
      },
    ],
    gate_decision: {
      allowed: false,
      reason: "unsupported_spot",
      confidence: 0,
    },
  };
}
