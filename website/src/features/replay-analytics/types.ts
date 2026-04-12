export type ReplayAnalyticsPayloadSource =
  | "runtime_snapshot"
  | "fixture"
  | "manual"
  | "offline_fallback"

export type ReplayAnalyticsDirection = "up" | "down" | "flat"

export type ReplayAnalyticsSeverity = "low" | "medium" | "high" | "critical"

export type ReplayHandStreet = "preflop" | "flop" | "turn" | "river" | "showdown"

export type ReplayHandReviewStatus =
  | "new"
  | "in_review"
  | "tagged"
  | "resolved"
  | "archived"

export type ReplayHandPriority = "low" | "medium" | "high"

export interface ReplayAnalyticsOverview {
  totalSessions: number
  totalHands: number
  reviewedHands: number
  taggedLeaks: number
  netBb: number
  evBb: number
  bbPer100: number
  averagePotBb: number
  winRate: number
  bestSessionId: string | null
  mostImportantLeakId: string | null
}

export interface ReplaySessionSummary {
  sessionId: string
  label: string
  startedAt: string
  endedAt: string
  variant: string
  stakes: string
  tableName: string
  seats: number
  handsPlayed: number
  reviewedHands: number
  netBb: number
  evBb: number
  bbPer100: number
  showdownRate: number
  vpip: number
  pfr: number
  aggressionFactor: number
  notes: string
  tags: string[]
  status: "complete" | "running" | "partial"
}

export interface ReplayTrendMetric {
  id: string
  label: string
  group: string
  value: number
  previousValue: number
  delta: number
  direction: ReplayAnalyticsDirection
  unit: string
  severity: ReplayAnalyticsSeverity
  description: string
}

export interface ReplayTaggedLeak {
  id: string
  tag: string
  title: string
  category: string
  description: string
  impact: string
  confidence: number
  frequency: number
  severity: ReplayAnalyticsSeverity
  sampleHandIds: string[]
  recommendedFocus: string
  evidence: string[]
}

export interface ReplayHandActionStep {
  street: ReplayHandStreet
  actor: string
  action: string
  sizeBb?: number
  potBbAfter?: number
  note?: string
}

export interface ReplayReviewableHandSpot {
  handSpotId: string
  sessionId: string
  handNumber: number
  label: string
  street: ReplayHandStreet
  heroCards: string[]
  board: string[]
  heroPosition: string
  villainPosition: string
  stackBb: number
  potBb: number
  effectiveStackBb: number
  actionLine: ReplayHandActionStep[]
  tags: string[]
  reviewStatus: ReplayHandReviewStatus
  priority: ReplayHandPriority
  recommendedFocus: string
  createdAt: string
}

export interface ReplayAnalyticsPayload {
  payloadVersion: 1
  source: ReplayAnalyticsPayloadSource
  generatedAt: string
  overview: ReplayAnalyticsOverview
  sessionSummaries: ReplaySessionSummary[]
  trendMetrics: ReplayTrendMetric[]
  taggedLeaks: ReplayTaggedLeak[]
  reviewableHandSpots: ReplayReviewableHandSpot[]
}

export interface ReplayPolicyCompareAggregate {
  scopeLabel?: string
  scopeBadge?: string
  sessionLabel?: string
  comparedSpots: number
  deltaSpots: number
  actionShiftSpots: number
  confidenceShiftSpots: number
  distinctContexts?: number
  coverageSummary?: string
  averageDeltaEv?: string
  strongestDeltaEv?: string
  topActionShift?: string
  topContext?: string
  topRecommendation?: string
  analysisHints?: string[]
  priorityLabels?: string[]
  pairwiseComparisons?: ReplayPolicyCompareSpotSnapshot[]
  comparisons?: ReplayPolicyCompareSpotSnapshot[]
  highlights?: ReplayPolicyCompareSpotSnapshot[]
}

export interface ReplayPolicyCompareSpotSnapshot {
  id: string
  title: string
  street?: string
  timestamp?: string
  policyA?: string
  policyB?: string
  policyPairKey?: string
  policyPairLabel?: string
  action?: string
  canonicalSpot?: string
  gateResult?: string
  note?: string
  deltaEv?: string
  actionShift?: string
  confidenceShift?: string
  confidence?: string
  impactScore?: number
  impactLabel?: string
}

export interface ReplayPolicyCompareExchange {
  kind: "policy_compare"
  version: 1
  exportedAt: string
  contractVersion?: string
  sessionLabel?: string
  source?: string
  aggregate?: ReplayPolicyCompareAggregate
  selectedSpot?: ReplayPolicyCompareSpotSnapshot
  raw?: unknown
}

export interface ReplayReviewPackSignal {
  label: string
  value: string
  note?: string
}

export interface ReplayReviewPackSpotSnapshot {
  id: string
  title: string
  street?: string
  timestamp?: string
  policyPairKey?: string
  policyPairLabel?: string
  action?: string
  result?: string
  heroEv?: string
  exploitability?: string
  confidence?: string
  canonicalSpot?: string
  gateResult?: string
  note?: string
  tags?: string[]
  runtimeMetrics?: string[]
  incidents?: string[]
  decisionTrace?: string[]
  spotDetails?: Array<{ label: string; value: string }>
  gateDetails?: Array<{ label: string; value: string }>
  traceDetails?: Array<{ label: string; value: string }>
  deltaEv?: string
  actionShift?: string
  confidenceShift?: string
  impactScore?: number
  impactLabel?: string
  reviewed?: boolean
  selected?: boolean
  chosenActionRaw?: string
  backend?: string
  cacheHit?: boolean
  evByAction?: Record<string, number>
  solverAlternatives?: Array<{
    action?: string
    rawAction?: string
    freq?: number
    ev?: number
    source?: string
  }>
}

export interface ReplayReviewPackCurrentReplay {
  selectedSpotId?: string
  selectedSpot?: ReplayReviewPackSpotSnapshot
  timelineCount: number
  sortedByImpact?: boolean
  impactSummary?: string
  policyCompare?: ReplayPolicyCompareAggregate
  signals?: ReplayReviewPackSignal[]
  timeline?: ReplayReviewPackSpotSnapshot[]
}

export interface ReplayReviewPack {
  kind: "review_pack"
  version: 1
  exportedAt: string
  contractVersion?: string
  locale?: "en" | "fr"
  sessionLabel?: string
  source?: string
  status?: string
  runtime?: {
    connected?: boolean
    transport?: string
    endpoint?: string
    refreshedAt?: string
  }
  analytics?: ReplayAnalyticsPayload
  currentReplay?: ReplayReviewPackCurrentReplay
  warnings?: string[]
  recommendations?: string[]
  notes?: string[]
  raw?: unknown
}

export interface ReplayAnalyticsRuntimeSnapshot {
  generatedAt?: string
  payloadVersion?: number
  replayAnalytics?: unknown
  replay_analytics?: unknown
  analytics?: unknown
  overview?: unknown
  sessions?: unknown
  sessionSummaries?: unknown
  session_summaries?: unknown
  trendMetrics?: unknown
  trends?: unknown
  taggedLeaks?: unknown
  tagged_leaks?: unknown
  reviewableHandSpots?: unknown
  reviewable_hand_spots?: unknown
  handSpots?: unknown
  hand_spots?: unknown
  hands?: unknown
  aggregates?: unknown
  policyCompare?: unknown
  policy_compare?: unknown
  policyCompareAggregate?: unknown
  policy_compare_aggregate?: unknown
}
