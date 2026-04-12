export type BotCockpitSurface =
  | "bot_cockpit"
  | "solver_studio"
  | "replay_analytics"
  | "config_lab";

export type BotCockpitRuntimeState =
  | "idle"
  | "ready"
  | "streaming"
  | "degraded"
  | "offline"
  | "error";

export type BotCockpitOperatorMode =
  | "observe_only"
  | "assist"
  | "shadow"
  | "manual_override"
  | "diagnostic";

export type BotCockpitRuntimeSource =
  | "tauri"
  | "local_rest"
  | "browser_stub"
  | "legacy"
  | "unknown";

export type BotCockpitDecisionSource =
  | "native"
  | "http"
  | "fallback"
  | "legacy"
  | "browser_stub"
  | "unknown";

export type BotCockpitAlertSeverity = "info" | "success" | "warning" | "error";

export type CockpitHistoryViewMode = "runtime" | "persisted" | "combined";

export type BotCockpitAlertKind =
  | "runtime"
  | "ocr"
  | "solver"
  | "decision"
  | "fallback"
  | "network"
  | "operator"
  | "range"
  | "security"
  | "system"
  | "unknown";

export interface BotCockpitCardSnapshot {
  rank: string;
  suit: string;
  label?: string;
}

export interface BotCockpitDecisionAction {
  name: string;
  label: string;
  size: number | null;
  frequency: number;
  ev: number;
  isRecommended: boolean;
}

export interface BotCockpitAlertItem {
  id: string;
  kind: BotCockpitAlertKind;
  severity: BotCockpitAlertSeverity;
  title: string;
  message: string;
  createdAt: string;
  source: BotCockpitRuntimeSource | BotCockpitDecisionSource;
  dismissible: boolean;
  acknowledged: boolean;
  context: Record<string, unknown>;
}

export interface BotCockpitSpotSnapshot {
  id: string;
  label: string;
  street: "preflop" | "flop" | "turn" | "river";
  heroPosition: string;
  heroCards: BotCockpitCardSnapshot[];
  board: BotCockpitCardSnapshot[];
  heroRange: string;
  villainRanges: string[];
  legalActions: string[];
  actionHistory: string[];
  pot: number;
  effectiveStack: number;
  numPlayers: number;
  source: BotCockpitRuntimeSource;
  tableName: string;
  handId: string;
  ranges: Record<string, unknown>;
  ocr: Record<string, unknown>;
  notes: string[];
}

export interface BotCockpitDecisionSnapshot {
  chosenAction: string;
  actions: BotCockpitDecisionAction[];
  heroEv: number;
  exploitability: number;
  source: BotCockpitDecisionSource;
  warnings: string[];
  latencyMs: number;
  cacheHit: boolean;
  confidence: number;
  presetId: string;
  rationale: string;
}

export interface BotCockpitConnectionSnapshot {
  transport: "tauri" | "local_rest" | "browser_stub" | "offline";
  endpoint: string;
  reachable: boolean;
  httpStatus: number | null;
  latencyMs: number | null;
  lastCheckedAt: string;
}

export interface BotCockpitRuntimeSnapshot {
  status: BotCockpitRuntimeState;
  source: BotCockpitRuntimeSource;
  operatorMode: BotCockpitOperatorMode;
  surface: BotCockpitSurface;
  spot: BotCockpitSpotSnapshot;
  decision: BotCockpitDecisionSnapshot;
  alerts: BotCockpitAlertItem[];
  connection: BotCockpitConnectionSnapshot;
  sampleId: string;
  title: string;
  description: string;
  lastUpdatedAt: string;
  notes: string[];
  metrics: Record<string, unknown>;
}

export interface BotCockpitAlertSummary {
  total: number;
  open: number;
  acknowledged: number;
  info: number;
  success: number;
  warning: number;
  error: number;
  dominantSeverity: BotCockpitAlertSeverity | "none";
}

export interface BotCockpitTone {
  label: string;
  color: "default" | "primary" | "secondary" | "success" | "warning" | "error";
  description: string;
}

export interface BotCockpitState extends BotCockpitRuntimeSnapshot {
  statusTone: BotCockpitTone;
  operatorTone: BotCockpitTone;
  alertSummary: BotCockpitAlertSummary;
  summary: string;
}

export interface BotCockpitPayload {
  sampleId: string;
  title: string;
  description: string;
  runtime: BotCockpitRuntimeSnapshot;
}
