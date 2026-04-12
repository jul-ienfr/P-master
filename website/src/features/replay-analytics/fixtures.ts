import type {
  ReplayAnalyticsPayload,
  ReplayHandStreet,
  ReplayReviewableHandSpot,
  ReplaySessionSummary,
  ReplayTaggedLeak,
  ReplayTrendMetric,
} from "./types"

const defaultSessions: ReplaySessionSummary[] = [
  {
    sessionId: "session-2026-04-10-night-1",
    label: "Session du soir, spots cartographiés",
    startedAt: "2026-04-10T19:15:00.000Z",
    endedAt: "2026-04-10T22:05:00.000Z",
    variant: "NLHE",
    stakes: "NL25/NL50",
    tableName: "Arena-4",
    seats: 6,
    handsPlayed: 842,
    reviewedHands: 18,
    netBb: 41.5,
    evBb: 57.2,
    bbPer100: 4.93,
    showdownRate: 0.29,
    vpip: 24.4,
    pfr: 18.1,
    aggressionFactor: 2.67,
    notes: "La baisse de résultat river vient de deux nœuds d'overbluff et d'une thin value manquée.",
    tags: ["river", "thin-value", "overbluff"],
    status: "complete",
  },
  {
    sessionId: "session-2026-04-11-afternoon-2",
    label: "Bloc d'étude court",
    startedAt: "2026-04-11T13:10:00.000Z",
    endedAt: "2026-04-11T14:02:00.000Z",
    variant: "NLHE",
    stakes: "NL10/NL25",
    tableName: "Lab-2",
    seats: 6,
    handsPlayed: 214,
    reviewedHands: 9,
    netBb: -8.75,
    evBb: 2.1,
    bbPer100: -4.09,
    showdownRate: 0.25,
    vpip: 22.1,
    pfr: 16.7,
    aggressionFactor: 2.11,
    notes: "Bonne structure préflop, mais les sizings de c-bet ont dérivé sur les low boards sous pression.",
    tags: ["c-bet", "low-board", "study"],
    status: "running",
  },
]

const defaultTrendMetrics: ReplayTrendMetric[] = [
  {
    id: "trend-vpip",
    label: "Tendance VPIP",
    group: "preflop",
    value: 23.8,
    previousValue: 22.9,
    delta: 0.9,
    direction: "up",
    unit: "%",
    severity: "low",
    description: "Participation préflop légèrement plus large sur les trois dernières sessions.",
  },
  {
    id: "trend-pfr",
    label: "Tendance PFR",
    group: "preflop",
    value: 17.4,
    previousValue: 18.6,
    delta: -1.2,
    direction: "down",
    unit: "%",
    severity: "medium",
    description: "La fréquence de raise a ralenti en position tardive, probablement liée à une sélection de tables plus serrée.",
  },
  {
    id: "trend-river-ev",
    label: "Tendance EV river",
    group: "postflop",
    value: -2.4,
    previousValue: -5.7,
    delta: 3.3,
    direction: "up",
    unit: "bb",
    severity: "medium",
    description: "La qualité des décisions river s'est améliorée après correction des seuils de défense contre les block bets.",
  },
  {
    id: "trend-leak-rate",
    label: "Taux de leaks tagués",
    group: "review",
    value: 2.1,
    previousValue: 3.2,
    delta: -1.1,
    direction: "down",
    unit: "pour 100 mains",
    severity: "high",
    description: "Les sessions de review réduisent le nombre de leaks répétables par unité de volume.",
  },
]

const defaultTaggedLeaks: ReplayTaggedLeak[] = [
  {
    id: "leak-river-overbluff",
    tag: "river",
    title: "Overbluff sur boards cappés",
    category: "postflop",
    description: "L'agression river reste trop élevée quand les ranges adverses paraissent sous-représentées mais collent encore trop.",
    impact: "Perte d'EV importante sur les spots river à faible SPR.",
    confidence: 0.88,
    frequency: 0.14,
    severity: "high",
    sampleHandIds: ["hand-842-17", "hand-842-41"],
    recommendedFocus: "Comparer la densité de bluffs aux nœuds river validés par le solver.",
    evidence: ["Hypothèses de fold equity trop hautes", "Faible élasticité de call-down", "Blockers mal exploités"],
  },
  {
    id: "leak-cbet-lowboard",
    tag: "c-bet",
    title: "Dérive de sizing sur low boards",
    category: "flop",
    description: "Les c-bets flop oscillent entre sizings trop gros et trop petits sur les low boards pairés.",
    impact: "Incohérence stratégique sur des textures de board comparables.",
    confidence: 0.81,
    frequency: 0.19,
    severity: "medium",
    sampleHandIds: ["hand-214-03", "hand-214-12"],
    recommendedFocus: "Verrouiller la branche small bet sur les low boards dynamiques.",
    evidence: ["Mauvaise lecture de texture", "Sensibilité au SPR", "Écart solver sur runouts pairés"],
  },
  {
    id: "leak-thin-value",
    tag: "thin-value",
    title: "Thin value manquée en position",
    category: "value",
    description: "Les mises de value tardives laissent de l'argent sur la table quand les zones top pair ne sont pas assez pressées.",
    impact: "Perte d'EV modérée répartie sur beaucoup de petits pots.",
    confidence: 0.76,
    frequency: 0.11,
    severity: "medium",
    sampleHandIds: ["hand-842-05"],
    recommendedFocus: "Revoir les seuils de value sur les lines second pair et top pair kicker faible.",
    evidence: ["Réponse passive aux blockers", "Sous-mise aux seuils de showdown"],
  },
]

const defaultReviewableHandSpots: ReplayReviewableHandSpot[] = [
  {
    handSpotId: "spot-842-17-river",
    sessionId: "session-2026-04-10-night-1",
    handNumber: 842,
    label: "Bluff catch river contre ligne cappée",
    street: "river",
    heroCards: ["As", "Kd"],
    board: ["Qs", "Jd", "8c", "4h", "2d"],
    heroPosition: "BTN",
    villainPosition: "BB",
    stackBb: 87.4,
    potBb: 18.5,
    effectiveStackBb: 42.0,
    actionLine: [
      {
        street: "preflop",
        actor: "hero",
        action: "raise",
        sizeBb: 2.5,
        potBbAfter: 3.75,
      },
      {
        street: "flop",
        actor: "hero",
        action: "bet",
        sizeBb: 1.6,
        potBbAfter: 5.35,
      },
      {
        street: "turn",
        actor: "villain",
        action: "check-call",
        sizeBb: 4.0,
        potBbAfter: 13.35,
      },
      {
        street: "river",
        actor: "villain",
        action: "lead",
        sizeBb: 8.1,
        potBbAfter: 21.45,
      },
    ],
    tags: ["river", "bluff-catch", "capped-range"],
    reviewStatus: "in_review",
    priority: "high",
    recommendedFocus: "Vérifier la qualité des blockers et comparer la fréquence de call à la baseline solver.",
    createdAt: "2026-04-10T21:42:00.000Z",
  },
  {
    handSpotId: "spot-214-03-flop",
    sessionId: "session-2026-04-11-afternoon-2",
    handNumber: 214,
    label: "Branche de c-bet sur low board",
    street: "flop",
    heroCards: ["Kh", "Qh"],
    board: ["6s", "4d", "2c"],
    heroPosition: "CO",
    villainPosition: "BB",
    stackBb: 99.0,
    potBb: 5.1,
    effectiveStackBb: 78.5,
    actionLine: [
      {
        street: "preflop",
        actor: "hero",
        action: "raise",
        sizeBb: 2.2,
        potBbAfter: 3.3,
      },
      {
        street: "flop",
        actor: "hero",
        action: "bet",
        sizeBb: 1.9,
        potBbAfter: 5.2,
      },
    ],
    tags: ["c-bet", "low-board", "sizing"],
    reviewStatus: "tagged",
    priority: "medium",
    recommendedFocus: "Verrouiller la line small bet et inspecter les candidats au barrel turn.",
    createdAt: "2026-04-11T13:21:00.000Z",
  },
  {
    handSpotId: "spot-214-12-turn",
    sessionId: "session-2026-04-11-afternoon-2",
    handNumber: 214,
    label: "Probe turn après check flop",
    street: "turn",
    heroCards: ["Ah", "Tc"],
    board: ["9s", "7h", "2d", "5c"],
    heroPosition: "SB",
    villainPosition: "BB",
    stackBb: 63.0,
    potBb: 9.7,
    effectiveStackBb: 39.5,
    actionLine: [
      {
        street: "preflop",
        actor: "hero",
        action: "call",
        sizeBb: 1.0,
        potBbAfter: 2.0,
      },
      {
        street: "flop",
        actor: "villain",
        action: "check",
        potBbAfter: 2.0,
      },
      {
        street: "turn",
        actor: "hero",
        action: "bet",
        sizeBb: 3.2,
        potBbAfter: 5.2,
      },
    ],
    tags: ["probe", "turn", "range-advantage"],
    reviewStatus: "new",
    priority: "high",
    recommendedFocus: "Comparer la fréquence de probe à la range de protection check-back.",
    createdAt: "2026-04-11T13:35:00.000Z",
  },
]

function cloneHandSpot(spot: ReplayReviewableHandSpot): ReplayReviewableHandSpot {
  return {
    ...spot,
    heroCards: [...spot.heroCards],
    board: [...spot.board],
    tags: [...spot.tags],
    actionLine: spot.actionLine.map((step) => ({ ...step })),
  }
}

export function createDefaultReplayAnalyticsPayload(): ReplayAnalyticsPayload {
  return {
    payloadVersion: 1,
    source: "fixture",
    generatedAt: "2026-04-11T00:00:00.000Z",
    overview: {
      totalSessions: defaultSessions.length,
      totalHands: defaultSessions.reduce((sum, session) => sum + session.handsPlayed, 0),
      reviewedHands: defaultSessions.reduce((sum, session) => sum + session.reviewedHands, 0),
      taggedLeaks: defaultTaggedLeaks.length,
      netBb: defaultSessions.reduce((sum, session) => sum + session.netBb, 0),
      evBb: defaultSessions.reduce((sum, session) => sum + session.evBb, 0),
      bbPer100:
        defaultSessions.reduce((sum, session) => sum + session.bbPer100, 0) / defaultSessions.length,
      averagePotBb: 7.9,
      winRate: 0.62,
      bestSessionId: "session-2026-04-10-night-1",
      mostImportantLeakId: "leak-river-overbluff",
    },
    sessionSummaries: defaultSessions.map((session) => ({ ...session, tags: [...session.tags] })),
    trendMetrics: defaultTrendMetrics.map((metric) => ({ ...metric })),
    taggedLeaks: defaultTaggedLeaks.map((leak) => ({
      ...leak,
      sampleHandIds: [...leak.sampleHandIds],
      evidence: [...leak.evidence],
    })),
    reviewableHandSpots: defaultReviewableHandSpots.map(cloneHandSpot),
  }
}

export function createDefaultReplayAnalyticsSpot(
  street: ReplayHandStreet = "river",
): ReplayReviewableHandSpot {
  return cloneHandSpot(
    defaultReviewableHandSpots.find((spot) => spot.street === street) ?? defaultReviewableHandSpots[0],
  )
}

export function createDefaultReplayAnalyticsSessionSummaries(): ReplaySessionSummary[] {
  return defaultSessions.map((session) => ({ ...session }))
}

export function createDefaultReplayAnalyticsTrendMetrics(): ReplayTrendMetric[] {
  return defaultTrendMetrics.map((metric) => ({ ...metric }))
}

export function createDefaultReplayAnalyticsTaggedLeaks(): ReplayTaggedLeak[] {
  return defaultTaggedLeaks.map((leak) => ({ ...leak }))
}

export function createDefaultReplayAnalyticsHandSpots(): ReplayReviewableHandSpot[] {
  return defaultReviewableHandSpots.map((spot) => ({
    ...spot,
    actionLine: spot.actionLine.map((step) => ({ ...step })),
    heroCards: [...spot.heroCards],
    board: [...spot.board],
    tags: [...spot.tags],
  }))
}
