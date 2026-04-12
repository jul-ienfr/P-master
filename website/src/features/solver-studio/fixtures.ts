import {
  getDefaultSolverTreePresetId,
  getSolverTreePreset,
} from "./presets";
import type {
  SolveResponseV2Payload,
  SolverStudioSpot,
  SolverStudioSpotDraft,
} from "./types";

const defaultPreset = getSolverTreePreset(getDefaultSolverTreePresetId());

export const DEFAULT_SOLVER_STUDIO_SPOT: SolverStudioSpot = {
  id: "default-srp-hu-100bb",
  label: "Spot SRP HU par défaut",
  heroRange: "JJ+,AKs,AQs,AJs,KQs,AKo",
  villainRanges: ["22+,A2s+,K9s+,QTs+,JTs,T9s,98s,AJo+,KQo"],
  board: [...defaultPreset.defaultBoard],
  heroPosition: defaultPreset.defaultHeroPosition,
  startingPot: defaultPreset.defaultStartingPot,
  effectiveStack: defaultPreset.defaultEffectiveStack,
  actionHistory: [],
  treePresetId: defaultPreset.id,
  rake: 0,
  numPlayers: defaultPreset.recommendedNumPlayers,
  useCache: true,
  timeBudgetMs: defaultPreset.defaultTimeBudgetMs,
  street: defaultPreset.defaultStreet,
  tags: [...defaultPreset.tags, "default_fixture"],
  notes: "Exemple heads-up compatible avec le bridge /v2/solve courant.",
};

export const DEFAULT_SOLVER_STUDIO_DRAFT: SolverStudioSpotDraft = {
  label: DEFAULT_SOLVER_STUDIO_SPOT.label,
  heroRange: DEFAULT_SOLVER_STUDIO_SPOT.heroRange,
  villainRangesText: DEFAULT_SOLVER_STUDIO_SPOT.villainRanges.join("\n"),
  boardText: DEFAULT_SOLVER_STUDIO_SPOT.board.join(" "),
  heroPosition: DEFAULT_SOLVER_STUDIO_SPOT.heroPosition ?? "",
  startingPot: DEFAULT_SOLVER_STUDIO_SPOT.startingPot.toString(),
  effectiveStack: DEFAULT_SOLVER_STUDIO_SPOT.effectiveStack.toString(),
  actionHistoryText: DEFAULT_SOLVER_STUDIO_SPOT.actionHistory.join("\n"),
  treePresetId: DEFAULT_SOLVER_STUDIO_SPOT.treePresetId,
  rake: DEFAULT_SOLVER_STUDIO_SPOT.rake.toString(),
  numPlayers: DEFAULT_SOLVER_STUDIO_SPOT.numPlayers.toString(),
  useCache: DEFAULT_SOLVER_STUDIO_SPOT.useCache,
  timeBudgetMs: DEFAULT_SOLVER_STUDIO_SPOT.timeBudgetMs?.toString() ?? "",
  notes: DEFAULT_SOLVER_STUDIO_SPOT.notes,
};

export function createDefaultStudioSpot(): SolverStudioSpot {
  return {
    ...DEFAULT_SOLVER_STUDIO_SPOT,
    board: [...DEFAULT_SOLVER_STUDIO_SPOT.board],
    villainRanges: [...DEFAULT_SOLVER_STUDIO_SPOT.villainRanges],
    actionHistory: [...DEFAULT_SOLVER_STUDIO_SPOT.actionHistory],
    tags: [...DEFAULT_SOLVER_STUDIO_SPOT.tags],
  };
}

export function createDefaultStudioDraft(): SolverStudioSpotDraft {
  return {
    ...DEFAULT_SOLVER_STUDIO_DRAFT,
  };
}

export const DEFAULT_SOLVE_RESPONSE_V2_FIXTURE: SolveResponseV2Payload = {
  chosen_action: "bet_50",
  actions: [
    {
      name: "check",
      label: "Check",
      size: null,
      frequency: 0.34,
      ev: 1.12,
      is_recommended: false,
    },
    {
      name: "bet_50",
      label: "Mise 50%",
      size: 50,
      frequency: 0.49,
      ev: 1.31,
      is_recommended: true,
    },
    {
      name: "bet_100",
      label: "Mise 100%",
      size: 100,
      frequency: 0.17,
      ev: 1.08,
      is_recommended: false,
    },
  ],
  hero_ev: 1.31,
  exploitability: 0.18,
  cache_hit: true,
  elapsed_ms: 42,
  preset_id: DEFAULT_SOLVER_STUDIO_SPOT.treePresetId,
  warnings: [],
  confidence: 0.94,
  fallback_reason: null,
  incidents: [],
  gate_decision: {
    allowed: true,
    reason: "ready",
    confidence: 0.96,
  },
};
