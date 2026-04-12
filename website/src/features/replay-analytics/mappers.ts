import { createDefaultReplayAnalyticsPayload } from "./fixtures"
import type {
  ReplayAnalyticsDirection,
  ReplayAnalyticsOverview,
  ReplayAnalyticsPayload,
  ReplayAnalyticsPayloadSource,
  ReplayReviewPack,
  ReplayReviewPackCurrentReplay,
  ReplayReviewPackSignal,
  ReplayReviewPackSpotSnapshot,
  ReplayPolicyCompareAggregate,
  ReplayPolicyCompareExchange,
  ReplayPolicyCompareSpotSnapshot,
  ReplayAnalyticsRuntimeSnapshot,
  ReplayAnalyticsSeverity,
  ReplayHandPriority,
  ReplayHandReviewStatus,
  ReplayHandStreet,
  ReplayReviewableHandSpot,
  ReplaySessionSummary,
  ReplayTaggedLeak,
  ReplayTrendMetric,
} from "./types"

type Dictionary = Record<string, unknown>

function isRecord(value: unknown): value is Dictionary {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function asRecord(value: unknown): Dictionary | null {
  return isRecord(value) ? value : null
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function readString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback
}

function readNullableString(value: unknown, fallback: string | null = null): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback
}

function readNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}

function readStringArray(value: unknown): string[] {
  return asArray(value)
    .map((entry) => (typeof entry === "string" ? entry : ""))
    .filter((entry) => entry.length > 0)
}

function readDirection(value: unknown, fallback: ReplayAnalyticsDirection = "flat"): ReplayAnalyticsDirection {
  return value === "up" || value === "down" || value === "flat" ? value : fallback
}

function readSeverity(
  value: unknown,
  fallback: ReplayAnalyticsSeverity = "low",
): ReplayAnalyticsSeverity {
  return value === "low" || value === "medium" || value === "high" || value === "critical"
    ? value
    : fallback
}

function readStreet(value: unknown, fallback: ReplayHandStreet = "flop"): ReplayHandStreet {
  return value === "preflop" || value === "flop" || value === "turn" || value === "river" || value === "showdown"
    ? value
    : fallback
}

function readReviewStatus(
  value: unknown,
  fallback: ReplayHandReviewStatus = "new",
): ReplayHandReviewStatus {
  return value === "new" || value === "in_review" || value === "tagged" || value === "resolved" || value === "archived"
    ? value
    : fallback
}

function readPriority(value: unknown, fallback: ReplayHandPriority = "medium"): ReplayHandPriority {
  return value === "low" || value === "medium" || value === "high" ? value : fallback
}

function readSource(
  value: unknown,
  fallback: ReplayAnalyticsPayloadSource = "offline_fallback",
): ReplayAnalyticsPayloadSource {
  return value === "runtime_snapshot" || value === "fixture" || value === "manual" || value === "offline_fallback"
    ? value
    : fallback
}

function readOptionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function formatSignedBb(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : ""
  return `${sign}${Math.abs(value).toFixed(2)} bb`
}

function readFormattedSignedMetric(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim().length > 0) {
    return value.trim()
  }

  const numeric = readOptionalNumber(value)
  return numeric === null ? undefined : formatSignedBb(numeric)
}

function readCount(value: unknown): number | null {
  const numeric = readOptionalNumber(value)
  return numeric === null ? null : Math.max(0, Math.round(numeric))
}

function readContractVersion(root: Dictionary): string | undefined {
  const meta = asRecord(root.meta)
  const contract = asRecord(root.contract) ?? asRecord(meta?.contract)
  const rawVersion =
    root.format_version ??
    root.formatVersion ??
    root.version_tag ??
    root.versionTag ??
    contract?.version ??
    meta?.version ??
    meta?.version_tag

  const value = readNullableString(rawVersion)
  return value ?? undefined
}

function readContractArtifactType(root: Dictionary): string | undefined {
  const meta = asRecord(root.meta)
  const contract = asRecord(root.contract) ?? asRecord(meta?.contract)
  return readNullableString(contract?.artifact_type ?? contract?.artifactType ?? meta?.artifact_type ?? meta?.artifactType) ?? undefined
}

function looksLikePolicyCompareAggregate(record: Dictionary | null): record is Dictionary {
  if (!record) {
    return false
  }

  return [
    "scopeBadge",
    "scope_badge",
    "sessionLabel",
    "session_label",
    "coverageSummary",
    "coverage_summary",
    "comparedSpots",
    "compared_spots",
    "deltaSpots",
    "delta_spots",
    "actionShiftSpots",
    "action_shift_spots",
    "confidenceShiftSpots",
    "confidence_shift_spots",
    "distinctContexts",
    "distinct_contexts",
    "averageDeltaEv",
    "average_delta_ev",
    "strongestDeltaEv",
    "strongest_delta_ev",
    "topActionShift",
    "top_action_shift",
    "analysisHints",
    "analysis_hints",
    "priorityLabels",
    "priority_labels",
  ].some((key) => key in record)
}

function readPolicyCompareSpotSnapshot(value: unknown): ReplayPolicyCompareSpotSnapshot | undefined {
  const record = asRecord(value)
  if (!record) {
    return undefined
  }

  const id = readString(record.id ?? record.spotId ?? record.spot_id, "")
  const title = readString(record.title ?? record.label, "")
  const canonicalSpot = readNullableString(record.canonicalSpot ?? record.canonical_spot)
  const street = readNullableString(record.street)
  const timestamp = readNullableString(record.timestamp ?? record.occurredAt ?? record.occurred_at)
  const policyA = readNullableString(
    record.policyA ?? record.policy_a ?? record.leftPolicy ?? record.left_policy ?? record.policyLeft ?? record.policy_left,
  )
  const policyB = readNullableString(
    record.policyB ?? record.policy_b ?? record.rightPolicy ?? record.right_policy ?? record.policyRight ?? record.policy_right,
  )
  const policyPairKey = readNullableString(record.policyPairKey ?? record.policy_pair_key)
  const policyPairLabel = readNullableString(record.policyPairLabel ?? record.policy_pair_label)
  const action = readNullableString(record.action)
  const gateResult = readNullableString(record.gateResult ?? record.gate_result)
  const note = readNullableString(record.note ?? record.recommendedFocus ?? record.recommended_focus)
  const deltaEv = readNullableString(record.deltaEv ?? record.delta_ev)
  const actionShift = readNullableString(record.actionShift ?? record.action_shift)
  const confidenceShift = readNullableString(record.confidenceShift ?? record.confidence_shift)
  const confidence = readNullableString(record.confidence)
  const impactScore = readOptionalNumber(record.impactScore ?? record.impact_score)
  const impactLabel = readNullableString(record.impactLabel ?? record.impact_label)

  if (
    !id &&
    !title &&
    !street &&
    !action &&
    !canonicalSpot &&
    !gateResult &&
    !note &&
    !deltaEv &&
    !actionShift &&
    !confidenceShift &&
    !confidence &&
    !impactLabel
  ) {
    return undefined
  }

  return {
    id: id || title || "policy-compare-import",
    title: title || canonicalSpot || "Imported policy compare",
    street: street ?? undefined,
    timestamp: timestamp ?? undefined,
    policyA: policyA ?? undefined,
    policyB: policyB ?? undefined,
    policyPairKey: policyPairKey ?? undefined,
    policyPairLabel: policyPairLabel ?? undefined,
    action: action ?? undefined,
    canonicalSpot: canonicalSpot ?? undefined,
    gateResult: gateResult ?? undefined,
    note: note ?? undefined,
    deltaEv: deltaEv ?? undefined,
    actionShift: actionShift ?? undefined,
    confidenceShift: confidenceShift ?? undefined,
    confidence: confidence ?? undefined,
    impactScore: impactScore ?? undefined,
    impactLabel: impactLabel ?? undefined,
  }
}

function readPolicyCompareContainers(root: Dictionary): Dictionary[] {
  const replayAnalytics = asRecord(root.replayAnalytics)
  const replayAnalyticsSnake = asRecord(root.replay_analytics)
  const analytics = asRecord(root.analytics)
  const summary = asRecord(root.summary)
  const aggregates = asRecord(root.aggregates)
  const replaySample = asRecord(asRecord(root.samples)?.replay_analytics)

  return [
    root,
    replayAnalytics,
    replayAnalyticsSnake,
    analytics,
    summary,
    replaySample,
    aggregates,
  ].filter((value): value is Dictionary => value !== null)
}

function readPolicyCompareCollection(
  containers: Dictionary[],
  aggregate: Dictionary,
  key: "comparisons" | "highlights" | "pairwiseComparisons",
): ReplayPolicyCompareSpotSnapshot[] {
  const candidateKeys =
    key === "pairwiseComparisons"
      ? [
          aggregate.pairwiseComparisons,
          aggregate.pairwise_comparisons,
          aggregate.pairwise,
          aggregate.pairs,
          aggregate.comparisons,
        ]
      : [aggregate[key]]

  const candidates: unknown[] = [...candidateKeys]

  for (const container of containers) {
    const policyCompare = asRecord(container.policyCompare ?? container.policy_compare)
    const nestedAggregates = asRecord(container.aggregates)
    candidates.push(
      container[key],
      key === "pairwiseComparisons" ? container.pairwiseComparisons ?? container.pairwise_comparisons ?? container.pairwise : undefined,
      asRecord(container.policyCompareAggregate ?? container.policy_compare_aggregate)?.[key],
      policyCompare?.[key],
      key === "pairwiseComparisons"
        ? policyCompare?.pairwiseComparisons ?? policyCompare?.pairwise_comparisons ?? policyCompare?.pairwise
        : undefined,
      asRecord(policyCompare?.aggregate)?.[key],
      key === "pairwiseComparisons"
        ? asRecord(policyCompare?.aggregate)?.pairwiseComparisons ??
          asRecord(policyCompare?.aggregate)?.pairwise_comparisons ??
          asRecord(policyCompare?.aggregate)?.pairwise
        : undefined,
      nestedAggregates?.[key],
      key === "pairwiseComparisons"
        ? nestedAggregates?.pairwiseComparisons ?? nestedAggregates?.pairwise_comparisons ?? nestedAggregates?.pairwise
        : undefined,
      asRecord(nestedAggregates?.policyCompare ?? nestedAggregates?.policy_compare)?.[key],
      key === "pairwiseComparisons"
        ? asRecord(nestedAggregates?.policyCompare ?? nestedAggregates?.policy_compare)?.pairwiseComparisons ??
          asRecord(nestedAggregates?.policyCompare ?? nestedAggregates?.policy_compare)?.pairwise_comparisons ??
          asRecord(nestedAggregates?.policyCompare ?? nestedAggregates?.policy_compare)?.pairwise
        : undefined,
    )
  }

  for (const candidate of candidates) {
    const limit = key === "pairwiseComparisons" ? 24 : 4
    const entries = asArray(candidate)
      .map((entry) => readPolicyCompareSpotSnapshot(entry))
      .filter((entry): entry is ReplayPolicyCompareSpotSnapshot => entry !== undefined)
      .slice(0, limit)
    if (entries.length > 0) {
      return entries
    }
  }

  return []
}

function readPolicyCompareAggregateRecord(root: Dictionary): Dictionary | null {
  const containers = readPolicyCompareContainers(root)

  for (const container of containers) {
    const policyCompare = asRecord(container.policyCompare ?? container.policy_compare)
    const nestedAggregates = asRecord(container.aggregates)
    const candidates = [
      asRecord(container.policyCompareAggregate ?? container.policy_compare_aggregate),
      asRecord(policyCompare?.aggregate),
      policyCompare,
      asRecord(nestedAggregates?.policyCompare ?? nestedAggregates?.policy_compare),
      nestedAggregates,
      container,
    ]

    for (const candidate of candidates) {
      if (looksLikePolicyCompareAggregate(candidate)) {
        return candidate
      }
    }
  }

  return null
}

export function readReplayPolicyCompareAggregate(
  runtimeSnapshot?: unknown,
  fallbackScopeLabel?: string,
): ReplayPolicyCompareAggregate | undefined {
  const root = asRecord(runtimeSnapshot)
  if (!root) {
    return undefined
  }

  const aggregate = readPolicyCompareAggregateRecord(root)
  if (!aggregate) {
    return undefined
  }
  const containers = readPolicyCompareContainers(root)

  const comparedSpots =
    readCount(aggregate.comparedSpots ?? aggregate.compared_spots ?? aggregate.spotsCompared ?? aggregate.spots_compared) ??
    0
  const deltaSpots =
    readCount(aggregate.deltaSpots ?? aggregate.delta_spots ?? aggregate.deltaEvSpots ?? aggregate.delta_ev_spots) ?? 0
  const actionShiftSpots =
    readCount(
      aggregate.actionShiftSpots ??
        aggregate.action_shift_spots ??
        aggregate.actionShiftCount ??
        aggregate.action_shift_count,
    ) ?? 0
  const confidenceShiftSpots =
    readCount(
      aggregate.confidenceShiftSpots ??
        aggregate.confidence_shift_spots ??
        aggregate.confidenceShiftCount ??
        aggregate.confidence_shift_count,
    ) ?? 0
  const normalizedComparedSpots = Math.max(comparedSpots, deltaSpots, actionShiftSpots, confidenceShiftSpots)

  const averageDeltaEv = readFormattedSignedMetric(
    aggregate.averageDeltaEv ?? aggregate.average_delta_ev ?? aggregate.avgDeltaEv ?? aggregate.avg_delta_ev,
  )
  const distinctContexts =
    readCount(aggregate.distinctContexts ?? aggregate.distinct_contexts ?? aggregate.contextCount ?? aggregate.context_count) ??
    0
  const strongestDeltaEv = readFormattedSignedMetric(
    aggregate.strongestDeltaEv ??
      aggregate.strongest_delta_ev ??
      aggregate.maxDeltaEv ??
      aggregate.max_delta_ev,
  )
  const topActionShift = readString(
    aggregate.topActionShift ?? aggregate.top_action_shift ?? aggregate.dominantActionShift ?? aggregate.dominant_action_shift,
    "",
  )
  const topContext = readString(
    aggregate.topContext ?? aggregate.top_context ?? aggregate.focusContext ?? aggregate.focus_context,
    "",
  )
  const topRecommendation = readString(
    aggregate.topRecommendation ??
      aggregate.top_recommendation ??
      aggregate.recommendedFocus ??
      aggregate.recommended_focus,
    "",
  )
  const scopeLabel = readString(aggregate.scopeLabel ?? aggregate.scope_label, fallbackScopeLabel ?? "")
  const scopeBadge = readString(aggregate.scopeBadge ?? aggregate.scope_badge, "")
  const sessionLabel = readString(aggregate.sessionLabel ?? aggregate.session_label, scopeLabel || (fallbackScopeLabel ?? ""))
  const coverageSummary = readString(aggregate.coverageSummary ?? aggregate.coverage_summary, "")
  const analysisHints = readStringArray(aggregate.analysisHints ?? aggregate.analysis_hints).slice(0, 3)
  const priorityLabels = readStringArray(aggregate.priorityLabels ?? aggregate.priority_labels).slice(0, 3)
  const pairwiseComparisons = readPolicyCompareCollection(containers, aggregate, "pairwiseComparisons")
  const comparisons = readPolicyCompareCollection(containers, aggregate, "comparisons")
  const highlights = readPolicyCompareCollection(containers, aggregate, "highlights")

  if (
    normalizedComparedSpots === 0 &&
    !averageDeltaEv &&
    !strongestDeltaEv &&
    !topActionShift &&
    !topContext &&
    !topRecommendation &&
    !coverageSummary &&
    analysisHints.length === 0 &&
    priorityLabels.length === 0 &&
    pairwiseComparisons.length === 0 &&
    comparisons.length === 0 &&
    highlights.length === 0
  ) {
    return undefined
  }

  return {
    scopeLabel: scopeLabel || undefined,
    scopeBadge: scopeBadge || undefined,
    sessionLabel: sessionLabel || undefined,
    comparedSpots: normalizedComparedSpots,
    deltaSpots,
    actionShiftSpots,
    confidenceShiftSpots,
    distinctContexts: distinctContexts || undefined,
    coverageSummary: coverageSummary || undefined,
    averageDeltaEv,
    strongestDeltaEv,
    topActionShift: topActionShift || undefined,
    topContext: topContext || undefined,
    topRecommendation: topRecommendation || undefined,
    analysisHints: analysisHints.length > 0 ? analysisHints : undefined,
    priorityLabels: priorityLabels.length > 0 ? priorityLabels : undefined,
    pairwiseComparisons: pairwiseComparisons.length > 0 ? pairwiseComparisons : undefined,
    comparisons: comparisons.length > 0 ? comparisons : undefined,
    highlights: highlights.length > 0 ? highlights : undefined,
  }
}

export function createReplayPolicyCompareExchange(input: {
  exportedAt?: string
  contractVersion?: string
  sessionLabel?: string
  source?: string
  aggregate?: ReplayPolicyCompareAggregate
  selectedSpot?: ReplayPolicyCompareSpotSnapshot
  raw?: unknown
}): ReplayPolicyCompareExchange {
  return {
    kind: "policy_compare",
    version: 1,
    exportedAt: readString(input.exportedAt, new Date().toISOString()),
    contractVersion: readNullableString(input.contractVersion) ?? undefined,
    sessionLabel: readNullableString(input.sessionLabel) ?? undefined,
    source: readNullableString(input.source) ?? undefined,
    aggregate: input.aggregate,
    selectedSpot: input.selectedSpot,
    raw: input.raw,
  }
}

function readReviewPackSignal(value: unknown): ReplayReviewPackSignal | undefined {
  const record = asRecord(value)
  if (!record) {
    return undefined
  }

  const label = readString(record.label, "")
  const currentValue = readString(record.value, "")
  const note = readNullableString(record.note)
  if (!label && !currentValue && !note) {
    return undefined
  }

  return {
    label: label || "signal",
    value: currentValue || "n/a",
    note: note ?? undefined,
  }
}

function readReviewPackKeyValueList(value: unknown): Array<{ label: string; value: string }> | undefined {
  const items = asArray(value)
    .map((entry) => {
      const record = asRecord(entry)
      if (!record) {
        return undefined
      }

      const label = readString(record.label, "")
      const currentValue = readString(record.value, "")
      if (!label && !currentValue) {
        return undefined
      }

      return {
        label: label || "detail",
        value: currentValue || "n/a",
      }
    })
    .filter((entry): entry is { label: string; value: string } => entry !== undefined)

  return items.length > 0 ? items : undefined
}

function readReviewPackSpotSnapshot(value: unknown): ReplayReviewPackSpotSnapshot | undefined {
  const record = asRecord(value)
  if (!record) {
    return undefined
  }

  const id = readString(record.id ?? record.spotId ?? record.spot_id, "")
  const title = readString(record.title ?? record.label, "")
  if (!id && !title) {
    return undefined
  }

  const rlDiff = asRecord(record.rlDiffSummary ?? record.rl_diff_summary)
  return {
    id: id || title,
    title: title || id || "review-spot",
    street: readNullableString(record.street) ?? undefined,
    timestamp: readNullableString(record.timestamp) ?? undefined,
    policyPairKey: readNullableString(record.policyPairKey ?? record.policy_pair_key) ?? undefined,
    policyPairLabel: readNullableString(record.policyPairLabel ?? record.policy_pair_label) ?? undefined,
    action: readNullableString(record.action) ?? undefined,
    result: readNullableString(record.result) ?? undefined,
    heroEv: readNullableString(record.heroEv ?? record.hero_ev) ?? undefined,
    exploitability: readNullableString(record.exploitability) ?? undefined,
    confidence: readNullableString(record.confidence) ?? undefined,
    canonicalSpot: readNullableString(record.canonicalSpot ?? record.canonical_spot) ?? undefined,
    gateResult: readNullableString(record.gateResult ?? record.gate_result) ?? undefined,
    note: readNullableString(record.note) ?? undefined,
    tags: readStringArray(record.tags),
    runtimeMetrics: readStringArray(record.runtimeMetrics ?? record.runtime_metrics),
    incidents: readStringArray(record.incidents),
    decisionTrace: readStringArray(record.decisionTrace ?? record.decision_trace),
    spotDetails: readReviewPackKeyValueList(record.spotDetails ?? record.spot_details),
    gateDetails: readReviewPackKeyValueList(record.gateDetails ?? record.gate_details),
    traceDetails: readReviewPackKeyValueList(record.traceDetails ?? record.trace_details),
    deltaEv: readNullableString(record.deltaEv ?? record.delta_ev ?? rlDiff?.deltaEv ?? rlDiff?.delta_ev) ?? undefined,
    actionShift:
      readNullableString(record.actionShift ?? record.action_shift ?? rlDiff?.actionShift ?? rlDiff?.action_shift) ?? undefined,
    confidenceShift:
      readNullableString(
        record.confidenceShift ?? record.confidence_shift ?? rlDiff?.confidenceShift ?? rlDiff?.confidence_shift,
      ) ?? undefined,
    impactScore: readOptionalNumber(record.impactScore ?? record.impact_score) ?? undefined,
    impactLabel: readNullableString(record.impactLabel ?? record.impact_label) ?? undefined,
    reviewed: typeof record.reviewed === "boolean" ? record.reviewed : undefined,
    selected: typeof record.selected === "boolean" ? record.selected : undefined,
    chosenActionRaw: readNullableString(record.chosenActionRaw ?? record.chosen_action_raw) ?? undefined,
    backend: readNullableString(record.backend) ?? undefined,
    cacheHit:
      typeof (record.cacheHit ?? record.cache_hit) === "boolean"
        ? Boolean(record.cacheHit ?? record.cache_hit)
        : undefined,
    evByAction: asRecord(record.evByAction ?? record.ev_by_action)
      ? Object.fromEntries(
          Object.entries(asRecord(record.evByAction ?? record.ev_by_action) ?? {}).flatMap(([key, rawValue]) => {
            const numericValue = readOptionalNumber(rawValue)
            return key.trim().length > 0 && numericValue !== undefined ? [[key, numericValue]] : []
          }),
        )
      : undefined,
    solverAlternatives: asArray(record.solverAlternatives ?? record.solver_alternatives ?? record.alternatives)
      .map((entry) => {
        const alternative = asRecord(entry)
        if (!alternative) {
          return undefined
        }

        const action = readNullableString(alternative.action) ?? undefined
        const rawAction = readNullableString(alternative.rawAction ?? alternative.raw_action) ?? undefined
        const freq = readOptionalNumber(alternative.freq)
        const ev = readOptionalNumber(alternative.ev)
        const source = readNullableString(alternative.source) ?? undefined
        if (!action && !rawAction && freq === undefined && ev === undefined && !source) {
          return undefined
        }
        return { action, rawAction, freq, ev, source }
      })
      .filter((entry) => entry !== undefined),
  }
}

function readReviewPackCurrentReplay(value: unknown): ReplayReviewPackCurrentReplay | undefined {
  const record = asRecord(value)
  if (!record) {
    return undefined
  }

  const selectedSpot = readReviewPackSpotSnapshot(record.selectedSpot ?? record.selected_spot)
  const timeline = asArray(record.timeline)
    .map((entry) => readReviewPackSpotSnapshot(entry))
    .filter((entry): entry is ReplayReviewPackSpotSnapshot => entry !== undefined)
  const policyCompare = readReplayPolicyCompareAggregate(record.policyCompare ?? record.policy_compare)
  const signals = asArray(record.signals)
    .map((entry) => readReviewPackSignal(entry))
    .filter((entry): entry is ReplayReviewPackSignal => entry !== undefined)

  const timelineCount = readCount(record.timelineCount ?? record.timeline_count) ?? timeline.length
  if (!selectedSpot && timeline.length === 0 && !policyCompare && signals.length === 0 && timelineCount === 0) {
    return undefined
  }

  return {
    selectedSpotId: readNullableString(record.selectedSpotId ?? record.selected_spot_id) ?? selectedSpot?.id,
    selectedSpot,
    timelineCount,
    sortedByImpact: typeof record.sortedByImpact === "boolean" ? record.sortedByImpact : undefined,
    impactSummary: readNullableString(record.impactSummary ?? record.impact_summary) ?? undefined,
    policyCompare: policyCompare ?? undefined,
    signals: signals.length > 0 ? signals : undefined,
    timeline: timeline.length > 0 ? timeline : undefined,
  }
}

export function createReplayReviewPack(input: {
  exportedAt?: string
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
}): ReplayReviewPack {
  return {
    kind: "review_pack",
    version: 1,
    exportedAt: readString(input.exportedAt, new Date().toISOString()),
    contractVersion: readNullableString(input.contractVersion) ?? undefined,
    locale: input.locale,
    sessionLabel: readNullableString(input.sessionLabel) ?? undefined,
    source: readNullableString(input.source) ?? undefined,
    status: readNullableString(input.status) ?? undefined,
    runtime: input.runtime
      ? {
          connected: input.runtime.connected,
          transport: readNullableString(input.runtime.transport) ?? undefined,
          endpoint: readNullableString(input.runtime.endpoint) ?? undefined,
          refreshedAt: readNullableString(input.runtime.refreshedAt) ?? undefined,
        }
      : undefined,
    analytics: input.analytics,
    currentReplay: input.currentReplay,
    warnings: input.warnings?.filter((entry) => entry.trim().length > 0),
    recommendations: input.recommendations?.filter((entry) => entry.trim().length > 0),
    notes: input.notes?.filter((entry) => entry.trim().length > 0),
    raw: input.raw,
  }
}

function createReplayImportTimelineEntry(spot: ReplayReviewPackSpotSnapshot): Dictionary {
  const decisionSnapshot: Dictionary = {
    action: spot.action,
    policy_pair_key: spot.policyPairKey,
    policy_pair_label: spot.policyPairLabel,
    chosen_action: spot.action,
    chosen_action_raw: spot.chosenActionRaw,
    confidence: spot.confidence,
    hero_ev: spot.heroEv,
    exploitability: spot.exploitability,
    incidents: spot.incidents,
    decision_trace: spot.decisionTrace,
    backend: spot.backend,
    cache_hit: spot.cacheHit,
    ev_by_action: spot.evByAction,
    alternatives: spot.solverAlternatives?.map((alternative) => ({
      action: alternative.action,
      raw_action: alternative.rawAction,
      freq: alternative.freq,
      ev: alternative.ev,
      source: alternative.source,
    })),
  }

  const runtimeMetrics = (spot.runtimeMetrics ?? []).filter((entry) => entry.trim().length > 0)
  if (runtimeMetrics.length > 0) {
    decisionSnapshot.runtime_metrics = runtimeMetrics
  }

  return {
    id: spot.id,
    label: spot.title,
    street: spot.street,
    created_at: spot.timestamp,
    policy_pair_key: spot.policyPairKey,
    policy_pair_label: spot.policyPairLabel,
    tags: spot.tags,
    recommendedFocus: spot.note,
    result_bb: spot.result ?? spot.heroEv,
    confidence: spot.confidence,
    spot_snapshot: {
      street: spot.street,
      canonical_spot: spot.canonicalSpot,
      metadata: {
        imported_from: "review_pack",
      },
    },
    decision_snapshot: decisionSnapshot,
    rl_diff_summary:
      spot.deltaEv || spot.actionShift || spot.confidenceShift
        ? {
            delta_ev: spot.deltaEv,
            action_shift: spot.actionShift,
            confidence_shift: spot.confidenceShift,
          }
        : undefined,
  }
}

export function createReplayAnalyticsBundleFromReviewPack(reviewPack: ReplayReviewPack): Dictionary {
  const analytics = reviewPack.analytics
  const timeline = reviewPack.currentReplay?.timeline ?? (reviewPack.currentReplay?.selectedSpot ? [reviewPack.currentReplay.selectedSpot] : [])

  return {
    kind: "review_pack_import",
    source: reviewPack.source ?? "local-json",
    status: reviewPack.status ?? "ready",
    exportedAt: reviewPack.exportedAt,
    warnings: reviewPack.warnings ?? [],
    recommendations: reviewPack.recommendations ?? [],
    notes: reviewPack.notes ?? [],
    runtime: reviewPack.runtime
      ? {
          connected: reviewPack.runtime.connected,
          transport: reviewPack.runtime.transport,
          endpoint: reviewPack.runtime.endpoint,
          refreshedAt: reviewPack.runtime.refreshedAt,
        }
      : undefined,
    replay_analytics: {
      source: analytics?.source ?? "manual",
      generatedAt: analytics?.generatedAt ?? reviewPack.exportedAt,
      summary: analytics
        ? {
            totalSessions: analytics.overview.totalSessions,
            totalHands: analytics.overview.totalHands,
            analyzedHands: analytics.overview.reviewedHands,
            totalWinningsBb: analytics.overview.netBb,
            evBbPer100: analytics.overview.evBb,
            winRateBbPer100: analytics.overview.winRate,
          }
        : undefined,
      sessions: analytics?.sessionSummaries,
      trends: analytics?.trendMetrics,
      tagged_leaks: analytics?.taggedLeaks,
      hands: analytics?.reviewableHandSpots,
      selected_session_id: reviewPack.sessionLabel,
      selected_spot_id: reviewPack.currentReplay?.selectedSpotId,
      sorted_by_impact: reviewPack.currentReplay?.sortedByImpact,
      impact_summary: reviewPack.currentReplay?.impactSummary,
      policy_compare: reviewPack.currentReplay?.policyCompare,
      signals: reviewPack.currentReplay?.signals,
      timeline: timeline.map((spot) => createReplayImportTimelineEntry(spot)),
      highlights: timeline.map((spot) => ({
        id: spot.id,
        title: spot.title,
        street: spot.street,
        result: spot.result ?? spot.heroEv,
        confidence: spot.confidence,
        tags: spot.tags,
        note: spot.note,
      })),
      replay_spot: reviewPack.currentReplay?.selectedSpot
        ? {
            street: reviewPack.currentReplay.selectedSpot.street,
            canonical_spot: reviewPack.currentReplay.selectedSpot.canonicalSpot,
            metadata: {
              view: reviewPack.currentReplay.selectedSpot.title,
            },
          }
        : undefined,
      replay_decision: reviewPack.currentReplay?.selectedSpot
        ? {
            chosen_action: reviewPack.currentReplay.selectedSpot.action,
            hero_ev: reviewPack.currentReplay.selectedSpot.heroEv,
            exploitability: reviewPack.currentReplay.selectedSpot.exploitability,
            confidence: reviewPack.currentReplay.selectedSpot.confidence,
            incidents: reviewPack.currentReplay.selectedSpot.incidents,
            decision_trace: reviewPack.currentReplay.selectedSpot.decisionTrace,
          }
        : undefined,
    },
    raw: reviewPack.raw,
  }
}

export function readReplayReviewPack(raw: unknown): ReplayReviewPack | undefined {
  const root = asRecord(raw)
  if (!root) {
    return undefined
  }

  const kind = readString(root.kind, "")
  const version = readNumber(root.version, 1)
  const contractVersion = readContractVersion(root)
  const artifactType = readContractArtifactType(root)
  const runtime = asRecord(root.runtime)
  const analytics = mapRuntimeSnapshotToReplayAnalyticsPayload((root.analytics ?? root.replayAnalytics ?? root.replay_analytics) as ReplayAnalyticsRuntimeSnapshot)
  const currentReplay = readReviewPackCurrentReplay(root.currentReplay ?? root.current_replay)
  const looksLikeReviewPack =
    kind === "review_pack" ||
    artifactType === "review_pack" ||
    (version === 1 && ("analytics" in root || "currentReplay" in root || "current_replay" in root))
  if (!looksLikeReviewPack) {
    return undefined
  }

  return {
    kind: "review_pack",
    version: 1,
    exportedAt: readString(root.exportedAt ?? root.exported_at, new Date().toISOString()),
    contractVersion,
    locale: root.locale === "fr" || root.locale === "en" ? root.locale : undefined,
    sessionLabel: readNullableString(root.sessionLabel ?? root.session_label) ?? undefined,
    source: readNullableString(root.source) ?? undefined,
    status: readNullableString(root.status) ?? undefined,
    runtime: runtime
      ? {
          connected: typeof runtime.connected === "boolean" ? runtime.connected : undefined,
          transport: readNullableString(runtime.transport) ?? undefined,
          endpoint: readNullableString(runtime.endpoint) ?? undefined,
          refreshedAt: readNullableString(runtime.refreshedAt ?? runtime.refreshed_at) ?? undefined,
        }
      : undefined,
    analytics,
    currentReplay,
    warnings: readStringArray(root.warnings),
    recommendations: readStringArray(root.recommendations),
    notes: readStringArray(root.notes),
    raw: root.raw,
  }
}

export function readReplayPolicyCompareExchange(raw: unknown): ReplayPolicyCompareExchange | undefined {
  const root = asRecord(raw)
  if (!root) {
    return undefined
  }

  const aggregate = readReplayPolicyCompareAggregate(raw)
  const selectedSpot = readPolicyCompareSpotSnapshot(
    root.selectedSpot ?? root.selected_spot ?? asRecord(root.policyCompare ?? root.policy_compare)?.selectedSpot,
  )
  const kind = readString(root.kind, "")
  const version = readNumber(root.version, 1)
  const contractVersion = readContractVersion(root)
  const artifactType = readContractArtifactType(root)
  const sessionLabel = readNullableString(root.sessionLabel ?? root.session_label)
  const source = readNullableString(root.source)
  const exportedAt = readString(root.exportedAt ?? root.exported_at, new Date().toISOString())
  const embeddedRaw = root.raw ?? root.runtimeSnapshot ?? root.runtime_snapshot

  const looksLikeExchange = kind === "policy_compare" || artifactType === "review_session" || version === 1
  if (!looksLikeExchange && !aggregate && !selectedSpot) {
    return undefined
  }

  return {
    kind: "policy_compare",
    version: 1,
    exportedAt,
    contractVersion,
    sessionLabel: sessionLabel ?? aggregate?.scopeLabel,
    source: source ?? undefined,
    aggregate,
    selectedSpot,
    raw: embeddedRaw ?? raw,
  }
}

function readOverview(value: unknown, fallback: ReplayAnalyticsOverview): ReplayAnalyticsOverview {
  const record = asRecord(value) ?? {}

  return {
    totalSessions: readNumber(record.totalSessions ?? record.total_sessions, fallback.totalSessions),
    totalHands: readNumber(record.totalHands ?? record.total_hands, fallback.totalHands),
    reviewedHands: readNumber(record.reviewedHands ?? record.reviewed_hands, fallback.reviewedHands),
    taggedLeaks: readNumber(record.taggedLeaks ?? record.tagged_leaks, fallback.taggedLeaks),
    netBb: readNumber(record.netBb ?? record.net_bb, fallback.netBb),
    evBb: readNumber(record.evBb ?? record.ev_bb, fallback.evBb),
    bbPer100: readNumber(record.bbPer100 ?? record.bb_per_100, fallback.bbPer100),
    averagePotBb: readNumber(record.averagePotBb ?? record.average_pot_bb, fallback.averagePotBb),
    winRate: readNumber(record.winRate ?? record.win_rate, fallback.winRate),
    bestSessionId: readNullableString(record.bestSessionId ?? record.best_session_id, fallback.bestSessionId),
    mostImportantLeakId: readNullableString(
      record.mostImportantLeakId ?? record.most_important_leak_id,
      fallback.mostImportantLeakId,
    ),
  }
}

function readSessionSummary(value: unknown, fallbackId: string): ReplaySessionSummary {
  const record = asRecord(value) ?? {}

  return {
    sessionId: readString(record.sessionId ?? record.session_id, fallbackId),
    label: readString(record.label, "Replay session"),
    startedAt: readString(record.startedAt ?? record.started_at, "2026-04-11T00:00:00.000Z"),
    endedAt: readString(record.endedAt ?? record.ended_at, "2026-04-11T00:00:00.000Z"),
    variant: readString(record.variant, "NLHE"),
    stakes: readString(record.stakes, "Unknown"),
    tableName: readString(record.tableName ?? record.table_name, "Unknown table"),
    seats: readNumber(record.seats, 6),
    handsPlayed: readNumber(record.handsPlayed ?? record.hands_played, 0),
    reviewedHands: readNumber(record.reviewedHands ?? record.reviewed_hands, 0),
    netBb: readNumber(record.netBb ?? record.net_bb, 0),
    evBb: readNumber(record.evBb ?? record.ev_bb, 0),
    bbPer100: readNumber(record.bbPer100 ?? record.bb_per_100, 0),
    showdownRate: readNumber(record.showdownRate ?? record.showdown_rate, 0),
    vpip: readNumber(record.vpip, 0),
    pfr: readNumber(record.pfr, 0),
    aggressionFactor: readNumber(record.aggressionFactor ?? record.aggression_factor, 0),
    notes: readString(record.notes, ""),
    tags: readStringArray(record.tags),
    status:
      record.status === "complete" || record.status === "running" || record.status === "partial"
        ? record.status
        : "partial",
  }
}

function readTrendMetric(value: unknown, fallbackId: string): ReplayTrendMetric {
  const record = asRecord(value) ?? {}

  return {
    id: readString(record.id ?? record.metric_id, fallbackId),
    label: readString(record.label, "Trend"),
    group: readString(record.group, "general"),
    value: readNumber(record.value, 0),
    previousValue: readNumber(record.previousValue ?? record.previous_value, 0),
    delta: readNumber(record.delta, 0),
    direction: readDirection(record.direction),
    unit: readString(record.unit, ""),
    severity: readSeverity(record.severity),
    description: readString(record.description, ""),
  }
}

function readTaggedLeak(value: unknown, fallbackId: string): ReplayTaggedLeak {
  const record = asRecord(value) ?? {}

  return {
    id: readString(record.id ?? record.leak_id, fallbackId),
    tag: readString(record.tag, "general"),
    title: readString(record.title, "Tagged leak"),
    category: readString(record.category, "general"),
    description: readString(record.description, ""),
    impact: readString(record.impact, ""),
    confidence: readNumber(record.confidence, 0),
    frequency: readNumber(record.frequency, 0),
    severity: readSeverity(record.severity),
    sampleHandIds: readStringArray(record.sampleHandIds ?? record.sample_hand_ids),
    recommendedFocus: readString(record.recommendedFocus ?? record.recommended_focus, ""),
    evidence: readStringArray(record.evidence),
  }
}

function readHandSpot(value: unknown, fallbackId: string): ReplayReviewableHandSpot {
  const record = asRecord(value) ?? {}
  const actionLine = asArray(record.actionLine ?? record.action_line).map((step) => {
    const stepRecord = asRecord(step) ?? {}

    return {
      street: readStreet(stepRecord.street),
      actor: readString(stepRecord.actor, "hero"),
      action: readString(stepRecord.action, "check"),
      sizeBb: typeof stepRecord.sizeBb === "number" ? stepRecord.sizeBb : undefined,
      potBbAfter: typeof stepRecord.potBbAfter === "number" ? stepRecord.potBbAfter : undefined,
      note: readString(stepRecord.note, ""),
    }
  })

  return {
    handSpotId: readString(record.handSpotId ?? record.hand_spot_id, fallbackId),
    sessionId: readString(record.sessionId ?? record.session_id, "session-unknown"),
    handNumber: readNumber(record.handNumber ?? record.hand_number, 0),
    label: readString(record.label, "Review spot"),
    street: readStreet(record.street),
    heroCards: readStringArray(record.heroCards ?? record.hero_cards),
    board: readStringArray(record.board),
    heroPosition: readString(record.heroPosition ?? record.hero_position, "BTN"),
    villainPosition: readString(record.villainPosition ?? record.villain_position, "BB"),
    stackBb: readNumber(record.stackBb ?? record.stack_bb, 0),
    potBb: readNumber(record.potBb ?? record.pot_bb, 0),
    effectiveStackBb: readNumber(record.effectiveStackBb ?? record.effective_stack_bb, 0),
    actionLine,
    tags: readStringArray(record.tags),
    reviewStatus: readReviewStatus(record.reviewStatus ?? record.review_status),
    priority: readPriority(record.priority),
    recommendedFocus: readString(record.recommendedFocus ?? record.recommended_focus, ""),
    createdAt: readString(record.createdAt ?? record.created_at, "2026-04-11T00:00:00.000Z"),
  }
}

export function mapRuntimeSnapshotToReplayAnalyticsPayload(
  runtimeSnapshot?: ReplayAnalyticsRuntimeSnapshot | null,
): ReplayAnalyticsPayload {
  if (!runtimeSnapshot) {
    return {
      ...createDefaultReplayAnalyticsPayload(),
      source: "offline_fallback",
    }
  }

  const root = asRecord(runtimeSnapshot) ?? {}
  const analytics =
    asRecord(root.replayAnalytics) ?? asRecord(root.replay_analytics) ?? asRecord(root.analytics) ?? root

  const defaultPayload = createDefaultReplayAnalyticsPayload()
  const hasSessions =
    "sessionSummaries" in analytics ||
    "session_summaries" in analytics ||
    "sessions" in analytics ||
    "sessionSummaries" in root ||
    "session_summaries" in root ||
    "sessions" in root
  const hasTrends =
    "trendMetrics" in analytics ||
    "trends" in analytics ||
    "trendMetrics" in root ||
    "trends" in root
  const hasLeaks =
    "taggedLeaks" in analytics ||
    "tagged_leaks" in analytics ||
    "taggedLeaks" in root ||
    "tagged_leaks" in root
  const hasHandSpots =
    "reviewableHandSpots" in analytics ||
    "reviewable_hand_spots" in analytics ||
    "handSpots" in analytics ||
    "hand_spots" in analytics ||
    "hands" in analytics ||
    "reviewableHandSpots" in root ||
    "reviewable_hand_spots" in root ||
    "handSpots" in root ||
    "hand_spots" in root ||
    "hands" in root
  const sessions = asArray(
    analytics.sessionSummaries ??
      analytics.session_summaries ??
      analytics.sessions ??
      root.sessionSummaries ??
      root.session_summaries ??
      root.sessions,
  )
  const trends = asArray(analytics.trendMetrics ?? analytics.trends ?? root.trendMetrics ?? root.trends)
  const leaks = asArray(
    analytics.taggedLeaks ?? analytics.tagged_leaks ?? root.taggedLeaks ?? root.tagged_leaks,
  )
  const handSpots = asArray(
    analytics.reviewableHandSpots ??
      analytics.reviewable_hand_spots ??
      analytics.handSpots ??
      analytics.hand_spots ??
      analytics.hands ??
      root.reviewableHandSpots ??
      root.reviewable_hand_spots ??
      root.handSpots ??
      root.hand_spots ??
      root.hands,
  )

  return {
    payloadVersion: 1,
    source: readSource(
      analytics.source ?? root.source ?? "runtime_snapshot",
      "runtime_snapshot",
    ),
    generatedAt: readString(
      analytics.generatedAt ?? analytics.generated_at ?? root.generatedAt ?? root.generated_at,
      new Date().toISOString(),
    ),
    overview: readOverview(
      analytics.overview ?? root.overview,
      defaultPayload.overview,
    ),
    sessionSummaries: hasSessions
      ? sessions.map((entry, index) => readSessionSummary(entry, `session-${index + 1}`))
      : defaultPayload.sessionSummaries,
    trendMetrics: hasTrends
      ? trends.map((entry, index) => readTrendMetric(entry, `trend-${index + 1}`))
      : defaultPayload.trendMetrics,
    taggedLeaks: hasLeaks
      ? leaks.map((entry, index) => readTaggedLeak(entry, `leak-${index + 1}`))
      : defaultPayload.taggedLeaks,
    reviewableHandSpots: hasHandSpots
      ? handSpots.map((entry, index) => readHandSpot(entry, `spot-${index + 1}`))
      : defaultPayload.reviewableHandSpots,
  }
}
