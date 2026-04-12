export type SolverStreet = "preflop" | "flop" | "turn" | "river";

export type SolverTreePresetId =
  | "srp_hu_100bb"
  | "srp_hu_texture_wet"
  | "3bp_hu_100bb"
  | "4bp_hu_100bb"
  | "turn_probe_hu"
  | "turn_delayed_cbet_hu"
  | "river_jam_low_spr"
  | "river_overbet_polar_hu"
  | (string & {});

export type SolverHeroPosition = "oop" | "ip" | "sb" | "bb" | "btn" | "button";

export type SolverDecisionWarning =
  | "unsupported_spot"
  | "approximate_ranges"
  | "multiway_approximation"
  | "timeout"
  | "cache_miss"
  | "fallback_used"
  | "ocr_low_confidence"
  | "model_unavailable"
  | "manual_override"
  | "unknown";

export interface SolverStudioSpot {
  id: string;
  label: string;
  heroRange: string;
  villainRanges: string[];
  board: string[];
  heroPosition: SolverHeroPosition | null;
  startingPot: number;
  effectiveStack: number;
  actionHistory: string[];
  treePresetId: SolverTreePresetId;
  rake: number;
  numPlayers: number;
  useCache: boolean;
  timeBudgetMs: number | null;
  street: SolverStreet;
  tags: string[];
  notes: string;
}

export interface SolverStudioSpotDraft {
  label: string;
  heroRange: string;
  villainRangesText: string;
  boardText: string;
  heroPosition: SolverHeroPosition | "";
  startingPot: string;
  effectiveStack: string;
  actionHistoryText: string;
  treePresetId: SolverTreePresetId;
  rake: string;
  numPlayers: string;
  useCache: boolean;
  timeBudgetMs: string;
  notes: string;
}

export interface SolveRequestV2Payload {
  hero_range: string;
  villain_ranges: string[];
  board: string[];
  starting_pot: number;
  effective_stack: number;
  hero_position: string | null;
  action_history: string[];
  tree_preset_id: SolverTreePresetId;
  rake: number;
  num_players: number;
  use_cache: boolean;
  time_budget_ms: number | null;
}

export interface SolveActionV2Payload {
  name: string;
  label: string;
  size: number | null;
  frequency: number;
  ev: number;
  is_recommended: boolean;
}

export interface SolveResponseV2Payload {
  chosen_action: string;
  actions: SolveActionV2Payload[];
  hero_ev: number;
  exploitability: number;
  cache_hit: boolean;
  elapsed_ms: number;
  preset_id: SolverTreePresetId;
  warnings: SolverDecisionWarning[];
   confidence?: number;
   fallback_reason?: string | null;
   incidents?: Array<{
     id: string;
     severity?: "info" | "warning" | "error";
     label?: string;
   }>;
   gate_decision?: {
     allowed?: boolean;
     reason?: string;
     confidence?: number;
   };
}

export interface SolverStudioAction {
  id: string;
  name: string;
  label: string;
  size: number | null;
  frequency: number;
  ev: number;
  recommended: boolean;
}

export interface SolverStudioResult {
  chosenAction: string;
  recommendedAction: SolverStudioAction | null;
  actions: SolverStudioAction[];
  heroEv: number;
  exploitability: number;
  cacheHit: boolean;
  elapsedMs: number;
  presetId: SolverTreePresetId;
  warnings: SolverDecisionWarning[];
  requestFingerprint: string;
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

export interface SolverTreePreset {
  id: SolverTreePresetId;
  label: string;
  family: "srp" | "3bet" | "4bet" | "turn" | "river";
  description: string;
  defaultHeroPosition: SolverHeroPosition;
  defaultStreet: SolverStreet;
  defaultStartingPot: number;
  defaultEffectiveStack: number;
  defaultBoard: string[];
  defaultTimeBudgetMs: number;
  recommendedNumPlayers: number;
  tags: string[];
}

export interface SolverStudioDraftIssue {
  field:
    | keyof SolverStudioSpotDraft
    | "board"
    | "villainRanges"
    | "heroPosition"
    | "compatibility";
  severity: "info" | "warning" | "error";
  message: string;
}

export interface SolverStudioDraftBuildResult {
  spot: SolverStudioSpot;
  request: SolveRequestV2Payload;
  issues: SolverStudioDraftIssue[];
}
