export type LlmProviderMode =
  | "disabled"
  | "openai_compatible_remote"
  | "openai_compatible_local";

export type LlmPrivacyMode = "strict_local" | "redacted_remote" | "full_remote";

export type LlmRole =
  | "analysis"
  | "operator_assistance"
  | "strategy_coach"
  | "replay_review";

export type LlmScope =
  | "spot"
  | "decision"
  | "replay"
  | "runtime"
  | "ocr"
  | "settings"
  | "fallback";

export type LlmAssistTaskKind =
  | "spot_explain"
  | "line_compare"
  | "decision_rationale"
  | "ocr_diagnostic"
  | "fallback_diagnostic"
  | "session_summary"
  | "strategy_review"
  | "replay_coach";

export interface LlmRoleMap extends Record<LlmRole, boolean> {}

export interface LlmScopeMap extends Record<LlmScope, boolean> {}

export interface PokerCardSnapshot {
  rank: string;
  suit: string;
  label?: string;
}

export interface SpotSnapshot {
  street: "preflop" | "flop" | "turn" | "river";
  heroPosition?: string;
  heroSeatId?: string;
  pot?: number;
  effectiveStack?: number;
  numPlayers?: number;
  heroCards?: PokerCardSnapshot[];
  board?: PokerCardSnapshot[];
  legalActions?: string[];
  actionHistory?: string[];
  ranges?: Record<string, unknown>;
  ocr?: Record<string, unknown>;
  source?: string;
}

export interface DecisionSnapshot {
  chosenAction?: string;
  observedHands?: number;
  alternatives?: Array<{
    name: string;
    size?: number;
    frequency?: number;
    ev?: number;
  }>;
  heroEv?: number;
  exploitability?: number;
  source?: "native" | "http" | "fallback" | "legacy";
  warnings?: string[];
  latencyMs?: number;
  confidence?: number;
  cacheHit?: boolean;
  gateDecision?: {
    allowed?: boolean;
    reason?: string;
    confidence?: number;
  };
  incidents?: Array<{
    id: string;
    severity?: "info" | "warning" | "error";
    kind?: string;
    label?: string;
  }>;
  fallbackHistory?: string[];
}

export interface ReplaySnapshot {
  replayId?: string;
  tableName?: string;
  handId?: string;
  summary?: string;
  notes?: string[];
}

export interface UiContextSnapshot {
  surface?: "solver_studio" | "bot_cockpit" | "replay_analytics" | "config_lab";
  selectedTab?: string;
  activePresetId?: string;
  operatorMode?: string;
}

export interface LlmConfig {
  enabled: boolean;
  providerMode: LlmProviderMode;
  baseUrl: string;
  apiKeyRef: string;
  model: string;
  temperature: number;
  maxOutputTokens: number;
  streaming: boolean;
  rolesEnabled: LlmRoleMap;
  contextScopesEnabled: LlmScopeMap;
  privacyMode: LlmPrivacyMode;
}

export interface LlmAssistTask {
  kind: LlmAssistTaskKind;
  title?: string;
  instruction?: string;
  focusScopes?: LlmScope[];
  spot?: SpotSnapshot;
  decision?: DecisionSnapshot;
  replay?: ReplaySnapshot;
  ui?: UiContextSnapshot;
}

export interface LlmAssistResponse {
  summary: string;
  recommendations: string[];
  warnings: string[];
  confidence: number;
  usedContext: string[];
  latencyMs: number;
  providerMetadata: Record<string, unknown>;
  rawText?: string;
}

export interface LlmProviderStatus {
  state: "disabled" | "ready" | "degraded" | "error" | "unknown";
  healthy: boolean;
  reason: string;
  providerMode: LlmProviderMode;
  baseUrl: string;
  model: string;
  apiKeyRef: string;
  latencyMs?: number | null;
  lastCheckedAt?: string | null;
}

export interface LlmAssistExecution {
  status: LlmProviderStatus;
  response: LlmAssistResponse;
}
