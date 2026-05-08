import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import UploadFileRoundedIcon from "@mui/icons-material/UploadFileRounded";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { LlmSettingsPanel, LlmWorkspace } from "../features/llm";
import type { LlmAssistTask } from "../features/llm";
import { createDefaultLlmConfig } from "../features/llm/config";
import {
  createReplayAnalyticsBundleFromReviewPack,
  createReplayReviewPack,
  createReplayPolicyCompareExchange,
  mapRuntimeSnapshotToReplayAnalyticsPayload,
  readReplayPolicyCompareAggregate,
  readReplayPolicyCompareExchange,
  readReplayReviewPack,
  type ReplayPolicyCompareSpotSnapshot,
} from "../features/replay-analytics";
import type { DecisionSnapshot, LlmConfig as UiLlmConfig, SpotSnapshot } from "../features/llm/types";
import {
  BotCockpitControlDesk,
  type CockpitHistoryViewMode,
  DecisionInsightsPanel,
  DecisionTracePanel,
  HistoryExportPanel,
  LiveTableSnapshotCard,
  RlDiffPanel,
  RuntimeMetricsCard,
  type DecisionTraceState,
  type OperatorAlert,
  type OperatorConsoleMode,
  type OperatorMetric,
} from "../features/bot-cockpit";
import {
  buildSolverStudioRequest,
  createDefaultStudioSpot,
  listSolverTreePresets,
  type SolveRequestV2Payload,
  type SolverStudioDraftIssue,
  type SolverStudioSpot,
  type SolverStudioSpotDraft,
} from "../features/solver-studio";
import {
  SolveResultsPanel,
  SpotNavigatorPanel,
  SpotBuilderForm,
  type CachedSolveEntry,
  type SolveResultsState,
  type SolverBackendState,
  type SolverStatusMetric,
  type SpotActionHistoryEntry,
  type SpotBuilderDraft,
} from "../features/solver-studio/components";
import {
  PolicyComparePanel,
  ReplayTimelinePanel,
  SessionOverviewPanel,
  type PolicyCompareAggregate,
  type ReplayAnalyticsState,
  type ReplayTimelineSpot,
  type SessionKpi,
  type SessionLeakGroup,
} from "../features/replay-analytics/components";
import {
  AutoAnnotatorPanel,
  InterfacePreferencesPanel,
  PresetLibraryPanel,
  RuntimeControlsPanel,
  OcrSettingsPanel,
  OcrProbePanel,
  type PresetPackItem,
  type PresetPackState,
  type PrivacyMode as ConfigLabPrivacySelection,
  type RuntimeReadinessState,
} from "../features/config-lab/components";
import {
  LLM_CONFIG_UPDATED_EVENT,
  loadRuntimeSnapshot,
  persistLlmConfig,
  runLocalLlmAssist,
  type RuntimeSnapshot,
} from "../lib/runtime";
import {
  createDefaultBotCockpitPayload,
  loadBotCockpitPayload,
  loadBotCockpitRuntimeHistory,
  persistBotCockpitOperatorState,
  refreshBotCockpitPayload,
  type BotCockpitDecisionSnapshot,
  type BotCockpitOperatorSnapshot,
  type BotCockpitPayload,
  type BotCockpitSpotSnapshot,
} from "../lib/botCockpit";
import {
  createDefaultReplayAnalyticsPayload,
  hydrateReplayAnalyticsPayloadFromBundle,
  loadReplayAnalyticsPayload,
  refreshReplayAnalyticsPayload,
  type ReplayAnalyticsPayload as ReplayBridgePayload,
} from "../lib/replayAnalytics";
import {
  loadConfigLabPayload,
  refreshConfigLabPayload,
  type ConfigLabPayload as ConfigBridgePayload,
  type ConfigLabOcrMode,
  type ConfigLabOcrStatus,
  type ConfigLabPrivacyMode as ConfigBridgePrivacyMode,
} from "../lib/configLab";
import {
  loadOcrConfig as loadPersistedOcrConfig,
  persistOcrConfig as persistStoredOcrConfig,
} from "../lib/ocrConfig";
import { useWorkstationThemeMode } from "../lib/theme";
import {
  getBotCopy,
  getConfigCopy,
  getReplayCopy,
  getWorkstationCopy,
  localizeGateReason,
  localizeHistoryEntryLabel,
  localizePrivacyModeLabel,
  localizeProviderModeLabel,
  localizeSourceLabel,
  t,
  useWorkstationText,
  type WorkstationCopy,
  type WorkstationLocale,
  WORKSTATION_COPY,
} from "../lib/workstationI18n";
import {
  getSolverStudioSampleSpots,
  loadSolverStudioDefaultSpot,
  runSolverStudioSolve,
  type SolverStudioSolveResult,
  type SolverStudioSpotPreset,
} from "../lib/solverStudio";

async function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

type SurfaceId = "solverStudio" | "botCockpit" | "replayAnalytics" | "configLab";

type Surface = {
  id: SurfaceId;
  path: string;
  accent: string;
  badge: string;
};

type Metric = {
  label: string;
  value: string;
  detail: string;
};

type Signal = {
  label: string;
  value: string;
  note: string;
};

type RawRecord = Record<string, unknown>;

type BotCockpitHistoryBundle = {
  version: 1;
  exportedAt: string;
  historyView: CockpitHistoryViewMode;
  availableHistoryViews: CockpitHistoryViewMode[];
  source: string | null;
  refreshedAt: string;
  tableName: string;
  handId: string;
  currentAction: string;
  decisionSource: string;
  persistedHistory: string[];
  runtimeHistory: string[];
  combinedHistory: string[];
  warningHistory: string[];
  fallbackHistory: string[];
  incidentHistory: string[];
};

type PolicyCompareImportState = {
  fileName: string;
  importedAt: string;
  sessionLabel: string;
  source: string;
};

type ReplayBundleImportResolution = {
  payload: ReplayBridgePayload;
  importedAt: string;
  sessionLabel?: string;
  selectedSpotId?: string;
  statusMessage?: string;
};

const surfaces: Surface[] = [
  {
    id: "solverStudio",
    path: "/solver-studio",
    accent: "amber",
    badge: "Base",
  },
  {
    id: "botCockpit",
    path: "/bot-cockpit",
    accent: "teal",
    badge: "Direct",
  },
  {
    id: "replayAnalytics",
    path: "/replay-analytics",
    accent: "violet",
    badge: "Revue",
  },
  {
    id: "configLab",
    path: "/config-lab",
    accent: "cyan",
    badge: "Pilotage",
  },
];

const WORKSTATION_LOCALE_STORAGE_KEY = "pokermaster:v2:locale";
const BOT_COCKPIT_HISTORY_VIEW_STORAGE_KEY = "pokermaster:v2:bot-cockpit-history-view";
const BOT_COCKPIT_HISTORY_BUNDLE_STORAGE_KEY = "pokermaster:v2:bot-cockpit-history-bundle";
const BOT_COCKPIT_DISPLAY_MODE_STORAGE_KEY = "pokermaster:v2:bot-cockpit-display-mode";
const BOT_COCKPIT_AUTO_REFRESH_MS = 1_500;
const DEFAULT_OCR_ENGINES = ["surya", "easyocr"];

type WorkstationI18nValue = {
  locale: WorkstationLocale;
  setLocale: (locale: WorkstationLocale) => void;
  copy: WorkstationCopy;
};

const WorkstationI18nContext = createContext<WorkstationI18nValue | null>(null);

function getReplayFallbackMetrics(locale: WorkstationLocale): Metric[] {
  return locale === "fr"
    ? [
        { label: "Mains indexées", value: "24.8k", detail: "Corpus replay consultable" },
        { label: "Leaks tagués", value: "18", detail: "Regroupés par line et par street" },
        { label: "Meilleure heure", value: "+12.4 bb", detail: "Suivie sur les sessions récentes" },
        { label: "Spots sauvés", value: "412", detail: "Prêts pour l’étude et la revue" },
      ]
    : [
        { label: "Hands indexed", value: "24.8k", detail: "Searchable replay corpus" },
        { label: "Tagged leaks", value: "18", detail: "Clustered by line and street" },
        { label: "Best hour", value: "+12.4 bb", detail: "Tracked from recent sessions" },
        { label: "Saved spots", value: "412", detail: "Ready for study and review" },
      ];
}

function getConfigFallbackMetrics(locale: WorkstationLocale): Metric[] {
  return locale === "fr"
    ? [
        { label: "Presets", value: "6 actifs", detail: "Packs d’arbres par famille de spots" },
        { label: "Backends", value: "2 prêts", detail: "Natif et fallback HTTP" },
        { label: "Confidentialité", value: "Strict local", detail: "Aucun contexte distant sans activation" },
        { label: "Suite de bench", value: "En ligne", detail: "Hooks PokerKit et RLCard" },
      ]
    : [
        { label: "Presets", value: "6 active", detail: "Tree packs by spot family" },
        { label: "Backends", value: "2 ready", detail: "Native and HTTP fallback" },
        { label: "Privacy", value: "Strict local", detail: "No remote context unless enabled" },
        { label: "Bench suite", value: "Online", detail: "PokerKit and RLCard hooks" },
      ];
}

function getActiveSurface(pathname: string) {
  return surfaces.find((surface) => pathname === surface.path) ?? surfaces[0];
}

function useWorkstationI18n() {
  const value = useContext(WorkstationI18nContext);
  if (!value) {
    throw new Error("Workstation i18n context is not available");
  }
  return value;
}

function getSurfaceText(surface: Surface, copy: WorkstationCopy) {
  return copy.surfaces[surface.id];
}

function taskForSurface(pathname: string): LlmAssistTask["kind"] {
  switch (pathname) {
    case "/bot-cockpit":
      return "ocr_diagnostic";
    case "/replay-analytics":
      return "session_summary";
    case "/config-lab":
      return "strategy_review";
    case "/solver-studio":
    default:
      return "spot_explain";
  }
}

function buildDefaultRuntimeSignals(copy: WorkstationCopy): Signal[] {
  const locale: WorkstationLocale = copy === WORKSTATION_COPY.fr ? "fr" : "en";
  return [
    {
      label: t(locale, (c) => c.runtimeSignals.solver),
      value: t(locale, (c) => c.common.nativeRust),
      note: t(locale, (c) => c.runtimeSignals.solverNote),
    },
    {
      label: t(locale, (c) => c.runtimeSignals.runtime),
      value: t(locale, (c) => c.common.loading),
      note: t(locale, (c) => c.runtimeSignals.runtimeNote),
    },
    {
      label: t(locale, (c) => c.runtimeSignals.fallback),
      value: t(locale, (c) => c.common.httpOn),
      note: t(locale, (c) => c.runtimeSignals.fallbackNote),
    },
    {
      label: t(locale, (c) => c.runtimeSignals.llm),
      value: t(locale, (c) => c.common.disabled),
      note: t(locale, (c) => c.runtimeSignals.llmNote),
    },
  ];
}

function buildRuntimeSignals(
  runtime: RuntimeSnapshot | null,
  runtimeError: string | null,
  copy: WorkstationCopy
): Signal[] {
  const defaultRuntimeSignals = buildDefaultRuntimeSignals(copy);
  if (!runtime) {
    return defaultRuntimeSignals.map((signal) =>
      signal.label === copy.runtimeSignals.runtime && runtimeError
        ? { ...signal, value: copy.common.observe, note: runtimeError }
        : signal
    );
  }

  return [
    {
      label: copy.runtimeSignals.solver,
      value: copy.common.nativeRust,
      note: copy.runtimeSignals.solverNote,
    },
    {
      label: copy.runtimeSignals.runtime,
      value: runtime.runtime,
      note:
        copy === WORKSTATION_COPY.fr
          ? `${localizeSourceLabel(runtime.source, "fr")} · hôte · v${runtime.version}`
          : `${runtime.source} host · v${runtime.version}`,
    },
    {
      label: copy.runtimeSignals.fallback,
      value: runtime.httpFallbackEnabled ? copy.common.httpOn : copy.common.httpOff,
      note: copy.runtimeSignals.fallbackNote,
    },
    {
      label: copy.runtimeSignals.llm,
      value: runtime.llm.enabled ? copy.common.enabled : copy.common.disabled,
      note: localizeProviderModeLabel(runtime.llm.providerMode, copy === WORKSTATION_COPY.fr ? "fr" : "en"),
    },
  ];
}

function SurfaceHero({
  title,
  subtitle,
  badge,
}: {
  title: string;
  subtitle: string;
  badge: string;
}) {
  return (
    <section className="surface-hero glass-card">
      <div className="surface-hero__eyebrow">
        <span className="pill pill--quiet">{badge}</span>
      </div>
      <div className="surface-hero__copy">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
    </section>
  );
}

function MetricGrid({ metrics }: { metrics: Metric[] }) {
  return (
    <div className="metric-grid">
      {metrics.map((metric) => (
        <article key={metric.label} className="metric-card glass-card">
          <span className="metric-card__label">{metric.label}</span>
          <strong className="metric-card__value">{metric.value}</strong>
          <span className="metric-card__detail">{metric.detail}</span>
        </article>
      ))}
    </div>
  );
}

function SectionCard({
  title,
  kicker,
  items,
  accent,
}: {
  title: string;
  kicker: string;
  items: string[];
  accent?: string;
}) {
  return (
    <article className={`section-card glass-card ${accent ? `section-card--${accent}` : ""}`}>
      <div className="section-card__header">
        <span className="section-card__kicker">{kicker}</span>
        <h2>{title}</h2>
      </div>
      <ul className="bullet-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </article>
  );
}

function SignalBoard({ signals }: { signals: Signal[] }) {
  return (
    <div className="signal-board glass-card">
      {signals.map((signal) => (
        <div key={signal.label} className="signal-row">
          <div>
            <span className="signal-row__label">{signal.label}</span>
            <p>{signal.note}</p>
          </div>
          <strong>{signal.value}</strong>
        </div>
      ))}
    </div>
  );
}

function prettifyWidgetValue(value: string | null | undefined, fallback: string) {
  if (!value || value.trim().length === 0) {
    return fallback;
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatWidgetCards(
  cards: SpotSnapshot["heroCards"] | SpotSnapshot["board"] | undefined,
  fallback: string
) {
  if (!cards || cards.length === 0) {
    return [fallback];
  }
  return cards.map((card) => card.label ?? `${card.rank ?? "?"}${card.suit ?? ""}`);
}

function formatWidgetPercent(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function formatWidgetLatency(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `${Math.round(value)} ms`;
}

function BotLiveWidget({
  locale,
  spot,
  decision,
  statusMessage,
  loading,
  paused,
  refreshLabel,
  refreshingLabel,
  pauseLabel,
  resumeLabel,
  onRefresh,
  onTogglePaused,
}: {
  locale: WorkstationLocale;
  spot: SpotSnapshot;
  decision: DecisionSnapshot | null | undefined;
  statusMessage: string;
  loading: boolean;
  paused: boolean;
  refreshLabel: string;
  refreshingLabel: string;
  pauseLabel: string;
  resumeLabel: string;
  onRefresh: () => void;
  onTogglePaused: () => void;
}) {
  const copy =
    locale === "fr"
      ? {
          kicker: "Widget live",
          title: "Panneau latéral",
          subtitle: "À garder ouvert pendant le jeu pour voir l’essentiel en direct.",
          action: "Action du bot",
          status: "État",
          confidence: "Confiance",
          latency: "Latence",
          pot: "Pot",
          stack: "Tapis",
          position: "Position",
          heroCards: "Tes cartes",
          board: "Board",
          legalActions: "Actions possibles",
          history: "Dernières actions",
          emptyHistory: "Aucune action récente.",
          emptyLegal: "Aucune action remontée.",
          waitingAction: "En attente",
          fullMode: "Vue complète",
          widgetMode: "Widget latéral",
        }
      : {
          kicker: "Live widget",
          title: "Side panel",
          subtitle: "Keep it open during play to see only the live essentials.",
          action: "Bot action",
          status: "Status",
          confidence: "Confidence",
          latency: "Latency",
          pot: "Pot",
          stack: "Stack",
          position: "Position",
          heroCards: "Your cards",
          board: "Board",
          legalActions: "Available actions",
          history: "Latest actions",
          emptyHistory: "No recent action.",
          emptyLegal: "No action reported.",
          waitingAction: "Waiting",
          fullMode: "Full view",
          widgetMode: "Side widget",
        };

  const heroCards = formatWidgetCards(spot.heroCards, "—");
  const boardCards = formatWidgetCards(spot.board, "—");
  const recentHistory = (spot.actionHistory ?? []).slice(-4);
  const legalActions = spot.legalActions ?? [];

  return (
    <Box
      sx={{
        width: "100%",
        maxWidth: 420,
        display: "grid",
        gap: 2,
      }}
    >
      <Box
        className="glass-card"
        sx={{
          borderRadius: 5,
          p: { xs: 2, md: 2.5 },
          display: "grid",
          gap: 2,
        }}
      >
        <Box>
          <Typography variant="overline" sx={{ color: "#526173", letterSpacing: "0.16em" }}>
            {copy.kicker}
          </Typography>
          <Typography variant="h5">{copy.title}</Typography>
          <Typography variant="body2" sx={{ color: "#667085", mt: 0.75 }}>
            {copy.subtitle}
          </Typography>
        </Box>

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} useFlexGap flexWrap="wrap">
          <Button variant="contained" onClick={onRefresh} disabled={loading}>
            {loading ? refreshingLabel : refreshLabel}
          </Button>
          <Button variant="outlined" onClick={onTogglePaused}>
            {paused ? resumeLabel : pauseLabel}
          </Button>
        </Stack>

        <Box
          sx={{
            borderRadius: 4,
            border: "1px solid rgba(255,255,255,0.08)",
            background: "rgba(255,255,255,0.03)",
            p: 2,
          }}
        >
          <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
            {copy.action}
          </Typography>
          <Typography variant="h3" sx={{ mt: 0.5 }}>
            {prettifyWidgetValue(decision?.chosenAction, copy.waitingAction)}
          </Typography>
          <Typography variant="body2" sx={{ color: "#95a8c8", mt: 1 }}>
            {statusMessage}
          </Typography>
        </Box>

        <Box
          sx={{
            display: "grid",
            gap: 1,
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          }}
        >
          <Chip label={`${copy.confidence} · ${formatWidgetPercent(decision?.gateDecision?.confidence ?? decision?.confidence)}`} />
          <Chip label={`${copy.latency} · ${formatWidgetLatency(decision?.latencyMs)}`} />
          <Chip label={`${copy.pot} · ${spot.pot?.toFixed?.(1) ?? "—"} bb`} />
          <Chip label={`${copy.stack} · ${spot.effectiveStack?.toFixed?.(1) ?? "—"} bb`} />
        </Box>

        <Divider />

        <Stack spacing={1.5}>
          <Box>
            <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
              {copy.position}
            </Typography>
            <Typography variant="body1" sx={{ mt: 0.35 }}>
              {spot.heroPosition ?? "—"}
            </Typography>
          </Box>

          <Box>
            <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
              {copy.heroCards}
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 0.75 }}>
              {heroCards.map((card) => (
                <Chip key={`hero-${card}`} label={card} color="primary" variant="outlined" />
              ))}
            </Stack>
          </Box>

          <Box>
            <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
              {copy.board}
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 0.75 }}>
              {boardCards.map((card) => (
                <Chip key={`board-${card}`} label={card} variant="outlined" />
              ))}
            </Stack>
          </Box>

          <Box>
            <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
              {copy.legalActions}
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 0.75 }}>
              {(legalActions.length > 0 ? legalActions : [copy.emptyLegal]).map((action) => (
                <Chip key={action} label={prettifyWidgetValue(action, action)} variant="outlined" />
              ))}
            </Stack>
          </Box>

          <Box>
            <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
              {copy.history}
            </Typography>
            <Stack spacing={0.75} sx={{ mt: 0.75 }}>
              {recentHistory.length > 0 ? (
                recentHistory.map((entry, index) => (
                  <Typography key={`${entry}-${index}`} variant="body2" sx={{ color: "#dbe8fa" }}>
                    {index + 1}. {prettifyWidgetValue(entry, entry)}
                  </Typography>
                ))
              ) : (
                <Typography variant="body2" sx={{ color: "#95a8c8" }}>
                  {copy.emptyHistory}
                </Typography>
              )}
            </Stack>
          </Box>
        </Stack>
      </Box>
    </Box>
  );
}

function LlmDock({
  runtime,
  runtimeError,
  initialTask,
}: {
  runtime: RuntimeSnapshot | null;
  runtimeError: string | null;
  initialTask: LlmAssistTask["kind"];
}) {
  const { copy } = useWorkstationI18n();
  const locale: WorkstationLocale = copy === WORKSTATION_COPY.fr ? "fr" : "en";
  const [isOpen, setIsOpen] = useState(false);
  const llmState = runtime?.llm.enabled ? t(locale, (c) => c.common.enabled) : t(locale, (c) => c.common.disabled);
  const runtimeLabel = runtime
    ? `${runtime.runtime} · ${runtime.source} · v${runtime.version}`
    : t(locale, (c) => c.common.waitingHost);

  return (
    <aside className="llm-dock glass-card" aria-label="Dock assistant LLM">
      <div className="llm-dock__header">
        <div className="llm-dock__title-group">
          <span className="pill pill--quiet">{t(locale, (c) => c.assistant.badge)}</span>
          <div>
            <h3>{t(locale, (c) => c.assistant.title)}</h3>
            <p className="llm-dock__summary">{t(locale, (c) => c.assistant.summary)}</p>
          </div>
        </div>
        <div className="llm-dock__controls">
          <span className="llm-state">{llmState}</span>
          <Button variant="outlined" color="inherit" size="small" onClick={() => setIsOpen((open) => !open)}>
            {isOpen ? t(locale, (c) => c.assistant.hide) : t(locale, (c) => c.assistant.show)}
          </Button>
        </div>
      </div>
      <div className="llm-dock__runtime">
        <div className="runtime-row">
          <span>{t(locale, (c) => c.assistant.host)}</span>
          <strong>{runtimeLabel}</strong>
        </div>
        <div className="runtime-row">
          <span>{t(locale, (c) => c.assistant.privacy)}</span>
          <strong>{localizePrivacyModeLabel(runtime?.llm.privacyMode ?? "strict_local", copy === WORKSTATION_COPY.fr ? "fr" : "en")}</strong>
        </div>
        <div className="runtime-row">
          <span>{t(locale, (c) => c.assistant.provider)}</span>
          <strong>{localizeProviderModeLabel(runtime?.llm.providerMode ?? "disabled", copy === WORKSTATION_COPY.fr ? "fr" : "en")}</strong>
        </div>
      </div>
      {runtimeError ? <p className="llm-error">{runtimeError}</p> : null}
      {isOpen ? (
        <div className="llm-workspace-embed">
          <LlmWorkspace
            key={`${runtime?.source ?? "fallback"}:${runtime?.llm.providerMode ?? "disabled"}:${runtime?.llm.enabled ? "on" : "off"}`}
            initialConfig={runtime?.llm}
            initialTask={{ kind: initialTask }}
            persistConfig={async (config) => {
              await persistLlmConfig(config);
            }}
            runFallbackTask={runLocalLlmAssist}
          />
        </div>
      ) : (
        <p className="llm-dock__hint">{t(locale, (c) => c.assistant.hint)}</p>
      )}
    </aside>
  );
}

const CARD_TOKEN_PATTERN = /^[2-9TJQKA][shdc]$/i;
const CAPTURED_COCKPIT_SPOT_STORAGE_KEY = "pokermaster:v2:captured-cockpit-spot";

function inferStudioStreet(boardCards: string[]): SpotSnapshot["street"] {
  if (boardCards.length >= 5) {
    return "river";
  }
  if (boardCards.length === 4) {
    return "turn";
  }
  if (boardCards.length === 3) {
    return "flop";
  }
  return "preflop";
}

function createActionHistoryEntry(line: string): SpotActionHistoryEntry {
  return {
    actor: "",
    action: line,
    size: "",
    note: "",
  };
}

function formatActionHistoryEntry(entry: SpotActionHistoryEntry): string {
  return [entry.actor, entry.action, entry.size, entry.note]
    .map((value) => value.trim())
    .filter(Boolean)
    .join(" ");
}

function createSpotBuilderDraftFromPreset(preset: SolverStudioSpotPreset): SpotBuilderDraft {
  return {
    heroRange: preset.request.heroRange,
    villainRanges: [...preset.request.villainRanges],
    boardCards: [...preset.request.board],
    startingPot: preset.request.startingPot,
    effectiveStack: preset.request.effectiveStack,
    heroPosition: preset.request.heroPosition ?? "ip",
    actionHistory: preset.request.actionHistory.map(createActionHistoryEntry),
    treePresetId: preset.request.treePresetId,
    numPlayers: preset.request.numPlayers,
    timeBudgetMs: preset.request.timeBudgetMs ?? 1200,
  };
}

function createStudioDraftFromForm(
  value: SpotBuilderDraft,
  selectedSample: SolverStudioSpotPreset | null,
  locale: WorkstationLocale
): SolverStudioSpotDraft {
  return {
    label: selectedSample?.title ?? (locale === "fr" ? "Situation solveur manuelle" : "Manual Solver Spot"),
    heroRange: value.heroRange,
    villainRangesText: value.villainRanges.join("\n"),
    boardText: value.boardCards.join(" "),
    heroPosition: (value.heroPosition || "") as SolverStudioSpotDraft["heroPosition"],
    startingPot: value.startingPot.toString(),
    effectiveStack: value.effectiveStack.toString(),
    actionHistoryText: value.actionHistory.map(formatActionHistoryEntry).filter(Boolean).join("\n"),
    treePresetId: value.treePresetId as SolverStudioSpotDraft["treePresetId"],
    rake: "0",
    numPlayers: value.numPlayers.toString(),
    useCache: true,
    timeBudgetMs: value.timeBudgetMs.toString(),
    notes: selectedSample?.description ?? "",
  };
}

function mapSolveRequestToRuntimeRequest(
  request: SolveRequestV2Payload
) {
  return {
    heroRange: request.hero_range,
    villainRanges: [...request.villain_ranges],
    board: [...request.board],
    startingPot: request.starting_pot,
    effectiveStack: request.effective_stack,
    heroPosition: request.hero_position,
    actionHistory: [...request.action_history],
    treePresetId: request.tree_preset_id,
    rake: request.rake,
    numPlayers: request.num_players,
    useCache: request.use_cache,
    timeBudgetMs: request.time_budget_ms,
  };
}

function parseCardSnapshots(cards: string[]) {
  return cards
    .filter((card) => CARD_TOKEN_PATTERN.test(card))
    .map((card) => ({
      rank: card.slice(0, -1).toUpperCase(),
      suit: card.slice(-1).toLowerCase(),
      label: card,
    }));
}

function parseHeroCards(heroRange: string) {
  const compact = heroRange.replace(/\s+/g, "");
  if (/^[2-9TJQKA][shdc][2-9TJQKA][shdc]$/i.test(compact)) {
    return parseCardSnapshots([compact.slice(0, 2), compact.slice(2, 4)]);
  }

  const splitTokens = heroRange
    .split(/[\s,]+/)
    .map((token) => token.trim())
    .filter(Boolean);
  if (splitTokens.length === 2 && splitTokens.every((token) => CARD_TOKEN_PATTERN.test(token))) {
    return parseCardSnapshots(splitTokens);
  }

  return undefined;
}

function loadCapturedCockpitPreset(locale: WorkstationLocale): SolverStudioSpotPreset | null {
  if (typeof localStorage === "undefined") {
    return null;
  }

  try {
    const rawValue = localStorage.getItem(CAPTURED_COCKPIT_SPOT_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }

    const payload = JSON.parse(rawValue) as {
      capturedAt?: string;
      spot?: BotCockpitSpotSnapshot;
      notes?: string[];
    };
    const spot = payload?.spot;
    if (!spot) {
      return null;
    }

    const heroRange =
      typeof spot.ranges?.hero === "string" && spot.ranges.hero.trim().length > 0
        ? spot.ranges.hero.trim()
        : spot.heroCards.join("");
    const villainRanges = Array.isArray(spot.ranges?.villains)
      ? spot.ranges.villains.filter(
          (entry): entry is string => typeof entry === "string" && entry.trim().length > 0
        )
      : [];
    const capturedAt = payload.capturedAt ?? new Date().toISOString();

    return {
      id: "captured-cockpit-spot",
      title: locale === "fr" ? "Situation capturée depuis le cockpit du bot" : "Captured Bot Cockpit Spot",
      description:
        locale === "fr"
          ? `Capturée depuis le cockpit du bot à ${capturedAt}.`
          : `Captured from Bot Cockpit at ${capturedAt}.`,
      request: {
        heroRange,
        villainRanges: villainRanges.length > 0 ? villainRanges : ["QQ+,AK"],
        board: [...spot.board],
        startingPot: spot.pot,
        effectiveStack: spot.effectiveStack,
        heroPosition: spot.heroPosition,
        actionHistory: [...spot.actionHistory],
        treePresetId: "srp_hu_100bb",
        rake: 0,
        numPlayers: spot.numPlayers,
        useCache: true,
        timeBudgetMs: 1200,
      },
    };
  } catch {
    return null;
  }
}

function mapStudioSpotToSnapshot(
  spot: SolverStudioSpot,
  solveResult: SolverStudioSolveResult | null
): SpotSnapshot {
  return {
    street: inferStudioStreet(spot.board),
    heroPosition: spot.heroPosition ?? undefined,
    pot: spot.startingPot,
    effectiveStack: spot.effectiveStack,
    numPlayers: spot.numPlayers,
    heroCards: parseHeroCards(spot.heroRange),
    board: parseCardSnapshots(spot.board),
    legalActions: solveResult?.response.actions.map((action) => action.label || action.name),
    actionHistory: [...spot.actionHistory],
    ranges: {
      hero: spot.heroRange,
      villains: [...spot.villainRanges],
      notes: spot.notes,
    },
    source: "solver_studio",
  };
}

function mapSolveResultToDecisionSnapshot(
  solveResult: SolverStudioSolveResult | null
): DecisionSnapshot | null {
  if (!solveResult) {
    return null;
  }

  return {
    chosenAction:
      solveResult.response.chosenAction || solveResult.recommendedAction?.label || undefined,
    alternatives: solveResult.response.actions.map((action) => ({
      name: action.label || action.name,
      size: action.size ?? undefined,
      frequency: action.frequency,
      ev: action.ev,
    })),
    heroEv: solveResult.response.heroEv,
    exploitability: solveResult.response.exploitability,
    source:
      solveResult.status === "success"
        ? solveResult.transport.source === "http"
          ? "http"
          : "native"
        : "fallback",
    warnings: [...solveResult.response.warnings],
    latencyMs: solveResult.response.elapsedMs,
  };
}

function mapSolveResultToPanelState(
  solveResult: SolverStudioSolveResult | null,
  isSolving: boolean
): SolveResultsState {
  if (isSolving) {
    return "loading";
  }
  if (!solveResult) {
    return "idle";
  }
  if (solveResult.status === "error") {
    return "error";
  }
  if (solveResult.status === "offline") {
    return "offline_safe";
  }
  if (
    solveResult.warnings.includes("unsupported_spot") ||
    solveResult.warnings.includes("multiway_approximation")
  ) {
    return "unsupported";
  }
  if (solveResult.status === "fallback") {
    return "offline_safe";
  }
  return "ready";
}

function mapSolveResultToBackendState(
  solveResult: SolverStudioSolveResult | null,
  isSolving: boolean
): SolverBackendState {
  if (isSolving) {
    return "loading";
  }
  if (!solveResult || solveResult.status === "success") {
    return "ready";
  }
  if (solveResult.status === "offline") {
    return "offline";
  }
  return "degraded";
}

function buildSolverStatusMetrics(
  spot: SolverStudioSpot,
  solveResult: SolverStudioSolveResult | null,
  locale: WorkstationLocale
): SolverStatusMetric[] {
  const labels =
    locale === "fr"
      ? {
          preset: "Preset",
          street: "Étape",
          players: "Joueurs",
          latency: "Latence",
          awaitingRun: "En attente d'un calcul",
        }
      : {
          preset: "Preset",
          street: "Street",
          players: "Players",
          latency: "Latency",
          awaitingRun: "Awaiting run",
        };
  return [
    { label: labels.preset, value: spot.treePresetId },
    { label: labels.street, value: inferStudioStreet(spot.board) },
    { label: labels.players, value: String(spot.numPlayers) },
    {
      label: labels.latency,
      value: solveResult ? `${solveResult.response.elapsedMs} ms` : labels.awaitingRun,
    },
  ];
}

function buildStudioMetrics(
  spot: SolverStudioSpot,
  solveResult: SolverStudioSolveResult | null,
  statusMessage: string,
  selectedSample: SolverStudioSpotPreset | null,
  copy: WorkstationCopy,
  locale: WorkstationLocale
): Metric[] {
  const studio = t(locale, (c) => c.solverStudio);
  const common = t(locale, (c) => c.common);
  return [
    {
      label: studio.metrics.preset,
      value: spot.treePresetId,
      detail: selectedSample?.description ?? studio.metricDetails.preset,
    },
    {
      label: studio.metrics.board,
      value: spot.board.length > 0 ? spot.board.join(" ") : studio.metricDetails.boardPreflop,
      detail: `${locale === "fr" ? "Étape" : "Street"} · ${inferStudioStreet(spot.board)}`,
    },
    {
      label: studio.metrics.source,
      value: solveResult ? solveResult.transport.source : common.observe,
      detail: solveResult ? solveResult.message : studio.metricDetails.noSolve,
    },
    {
      label: studio.metrics.recommendation,
      value: solveResult?.recommendedAction?.label ?? studio.metricDetails.waitingRecommendation,
      detail: statusMessage,
    },
  ];
}

function issueSeverity(
  issues: SolverStudioDraftIssue[]
): "info" | "warning" | "error" {
  if (issues.some((issue) => issue.severity === "error")) {
    return "error";
  }
  if (issues.some((issue) => issue.severity === "warning")) {
    return "warning";
  }
  return "info";
}

function localizeSolveStatus(status: SolverStudioSolveResult["status"] | undefined, locale: WorkstationLocale) {
  const labels =
    locale === "fr"
      ? {
          success: "prêt",
          fallback: "secours",
          offline: "hors ligne",
          error: "erreur",
        }
      : {
          success: "ready",
          fallback: "fallback",
          offline: "offline",
          error: "error",
        };

  if (!status) {
    return locale === "fr" ? "vide" : "idle";
  }

  return labels[status];
}

function mapBotCockpitSpotToSnapshot(
  spot: BotCockpitSpotSnapshot,
  ocr: BotCockpitPayload["ocr"]
): SpotSnapshot {
  return {
    street: spot.street,
    heroPosition: spot.heroPosition ?? undefined,
    heroSeatId: spot.heroSeatId ?? undefined,
    pot: spot.pot,
    effectiveStack: spot.effectiveStack,
    numPlayers: spot.numPlayers,
    heroCards: parseCardSnapshots(spot.heroCards),
    board: parseCardSnapshots(spot.board),
    legalActions: [...spot.legalActions],
    actionHistory: [...spot.actionHistory],
    ranges: { ...spot.ranges },
    ocr: {
      confidence: ocr.confidence,
      drift: ocr.drift,
      frameLabel: ocr.frameLabel,
      notes: [...ocr.notes],
      source: ocr.source,
      ...spot.ocrMetadata,
    },
    source: spot.source,
  };
}

function dedupeHistoryValues(values: string[]): string[] {
  return values.filter(
    (value, index, array) => value.trim().length > 0 && array.indexOf(value) === index
  );
}

function readRuntimeHistoryEntries(value: unknown): string[] {
  return asRawArray(value)
    .map((entry) => {
      if (typeof entry === "string") {
        return entry;
      }

      const raw = asRawRecord(entry);
      const kind = readRawString(raw.kind, "");
      const message = readRawString(raw.message, "");
      if (!message) {
        return "";
      }
      return kind ? `${kind}: ${message}` : message;
    })
    .filter((entry) => entry.length > 0);
}

function deriveBotCockpitHistorySource(payload: BotCockpitPayload): string | null {
  const spotMetadata = asRawRecord(payload.spot.metadata);
  const decisionMetadata = asRawRecord(payload.decision.metadata);
  const candidates = [
    readRawString(spotMetadata.runtime_history_source, ""),
    readRawString(decisionMetadata.runtime_history_source, ""),
    readRawString(spotMetadata.source, ""),
    readRawString(decisionMetadata.source, ""),
    payload.spot.source,
    payload.source,
  ];

  return candidates.find((value) => value.trim().length > 0) ?? null;
}

function buildCockpitHistoryState(spot: BotCockpitPayload["spot"], runtimeHistoryOverride: string[] = []) {
  const metadata = asRawRecord(spot.metadata);
  const persisted = dedupeHistoryValues([
    ...spot.actionHistory,
    ...readRawStringArray(metadata.action_history),
  ]).slice(-8);
  const runtime = dedupeHistoryValues([
    ...runtimeHistoryOverride,
    ...readRuntimeHistoryEntries(metadata.runtime_event_history),
  ]).slice(-8);
  const combined = dedupeHistoryValues([...persisted, ...runtime]).slice(-8);
  const availableModes: CockpitHistoryViewMode[] = [
    combined.length > 0 ? "combined" : null,
    persisted.length > 0 ? "persisted" : null,
    runtime.length > 0 ? "runtime" : null,
  ].filter((mode): mode is CockpitHistoryViewMode => mode !== null);

  return { persisted, runtime, combined, availableModes };
}

function parseBotCockpitHistoryBundle(value: string | null): BotCockpitHistoryBundle | null {
  if (!value) {
    return null;
  }

  try {
    const raw = JSON.parse(value) as Partial<BotCockpitHistoryBundle> | null;
    if (!raw || typeof raw !== "object") {
      return null;
    }

    const availableHistoryViews = Array.isArray(raw.availableHistoryViews)
      ? raw.availableHistoryViews.filter(
          (entry): entry is CockpitHistoryViewMode =>
            entry === "runtime" || entry === "persisted" || entry === "combined"
        )
      : [];

    return {
      version: 1,
      exportedAt: typeof raw.exportedAt === "string" ? raw.exportedAt : new Date().toISOString(),
      historyView: raw.historyView === "runtime" || raw.historyView === "persisted" ? raw.historyView : "combined",
      availableHistoryViews: availableHistoryViews.length > 0 ? availableHistoryViews : ["combined"],
      source: typeof raw.source === "string" && raw.source.trim().length > 0 ? raw.source : null,
      refreshedAt: typeof raw.refreshedAt === "string" ? raw.refreshedAt : "",
      tableName: typeof raw.tableName === "string" ? raw.tableName : "",
      handId: typeof raw.handId === "string" ? raw.handId : "",
      currentAction: typeof raw.currentAction === "string" ? raw.currentAction : "",
      decisionSource: typeof raw.decisionSource === "string" ? raw.decisionSource : "",
      persistedHistory: Array.isArray(raw.persistedHistory)
        ? raw.persistedHistory.filter((entry): entry is string => typeof entry === "string")
        : [],
      runtimeHistory: Array.isArray(raw.runtimeHistory)
        ? raw.runtimeHistory.filter((entry): entry is string => typeof entry === "string")
        : [],
      combinedHistory: Array.isArray(raw.combinedHistory)
        ? raw.combinedHistory.filter((entry): entry is string => typeof entry === "string")
        : [],
      warningHistory: Array.isArray(raw.warningHistory)
        ? raw.warningHistory.filter((entry): entry is string => typeof entry === "string")
        : [],
      fallbackHistory: Array.isArray(raw.fallbackHistory)
        ? raw.fallbackHistory.filter((entry): entry is string => typeof entry === "string")
        : [],
      incidentHistory: Array.isArray(raw.incidentHistory)
        ? raw.incidentHistory.filter((entry): entry is string => typeof entry === "string")
        : [],
    };
  } catch {
    return null;
  }
}

function mapBotCockpitDecisionToSnapshot(
  decision: BotCockpitDecisionSnapshot
): DecisionSnapshot {
  const metadata = asRawRecord(decision.metadata);
  const incidentValues = readRawStringArray(metadata.incidents);
  const decisionTraceHistory = asRawArray(metadata.decision_trace_history)
    .map((entry) => asRawRecord(entry))
    .map((entry) => {
      const action = readRawString(entry.chosen_action, "pending");
      const source = readRawString(entry.source, "runtime");
      const street = readRawString(entry.street, "spot").toLowerCase();
      return `${action} @ ${street} (${source})`;
    })
    .filter((entry) => entry.length > 0);
  const fallbackHistory = Array.from(
    new Set([
      ...readRawStringArray(metadata.fallback_history),
      ...decisionTraceHistory.filter((entry) => entry.includes("(fallback)")),
    ])
  );
  return {
    chosenAction: decision.chosenAction,
    alternatives: decision.alternatives.map((alternative) => ({
      name: alternative.name,
      size: alternative.size ?? undefined,
      frequency: alternative.frequency,
      ev: alternative.ev,
    })),
    heroEv: decision.heroEv,
    exploitability: decision.exploitability,
    source:
      decision.source === "native" ||
      decision.source === "http" ||
      decision.source === "fallback" ||
      decision.source === "legacy"
        ? decision.source
        : "native",
    warnings: [...decision.warnings],
    latencyMs: decision.latencyMs,
    confidence: decision.confidence,
    observedHands: readRawNumber(decision.observedHands, readRawNumber(metadata.observed_hands, 0)),
    cacheHit: Boolean(metadata.cache_hit),
    gateDecision: {
      allowed: metadata.gate_allowed !== false,
      reason: readRawString(metadata.gate_reason, "ready"),
      confidence: readRawNumber(decision.gateConfidence, readRawNumber(metadata.gate_confidence, decision.confidence)),
    },
    incidents: incidentValues.map((incidentId) => ({
      id: incidentId,
      severity:
        incidentId.includes("offline") || incidentId.includes("unavailable")
          ? "error"
          : incidentId.includes("low") || incidentId.includes("fallback")
            ? "warning"
            : "info",
      label: incidentId.replace(/_/g, " "),
    })),
    fallbackHistory,
  };
}

function mapBotCockpitDecisionState(
  payload: BotCockpitPayload | null,
  loading: boolean
): DecisionTraceState {
  if (loading) {
    return "loading";
  }
  if (!payload) {
    return "idle";
  }
  if (payload.state === "error") {
    return "error";
  }
  if (
    payload.state === "offline" ||
    payload.decision.source === "fallback" ||
    payload.decision.source === "legacy" ||
    payload.warnings.includes("fallback_used")
  ) {
    return "fallback";
  }
  if (!payload.decision.chosenAction && payload.decision.alternatives.length === 0) {
    return "idle";
  }
  return "ready";
}

function mapBotCockpitOperatorMode(
  operator: BotCockpitOperatorSnapshot,
  payload: BotCockpitPayload
): OperatorConsoleMode {
  if (operator.paused) {
    return "paused";
  }
  if (operator.manualOverrideEnabled) {
    return "manual_override";
  }
  if (operator.assistedModeEnabled) {
    return "assisted";
  }
  if (operator.observationModeEnabled) {
    return "observation";
  }
  if (operator.shadowModeEnabled) {
    return "shadow";
  }
  return payload.state === "live" ? "live" : "monitoring";
}

function buildBotCockpitAlerts(payload: BotCockpitPayload, locale: WorkstationLocale): OperatorAlert[] {
  const summary = describeBotCockpitPayload(payload, locale);
  const alerts: OperatorAlert[] = payload.warnings.map((warning) => ({
    id: warning,
    label: warning.replace(/_/g, " "),
    tone:
      warning === "host_unavailable" || warning === "runtime_offline"
        ? "error"
        : warning === "fallback_used" || warning === "ocr_low_confidence"
          ? "warning"
          : "info",
    detail: summary,
  }));

  if (alerts.length === 0) {
    const assisted = asRawRecord(payload.decision.metadata.assisted);
    const assistedActive = payload.operator.assistedModeEnabled;
    const assistedReady = assistedActive && Boolean(assisted.auto_execute);
    alerts.push({
      id: assistedActive ? "assisted" : payload.operator.observationModeEnabled ? "observation" : "runtime-ok",
      label:
        assistedActive
          ? locale === "fr"
            ? "assisté"
            : "assisted"
        : payload.operator.observationModeEnabled
          ? locale === "fr"
            ? "observation"
            : "observation"
          : payload.state === "live"
          ? locale === "fr"
            ? "runtime actif"
            : "runtime live"
          : locale === "fr"
            ? "surveillance"
            : "monitoring",
      tone: assistedActive ? (assistedReady ? "success" : "warning") : payload.operator.observationModeEnabled ? "info" : payload.state === "live" ? "success" : "info",
      detail: summary,
    });
  }

  return alerts;
}

function buildBotCockpitOperatorMetrics(
  payload: BotCockpitPayload,
  locale: WorkstationLocale
): OperatorMetric[] {
  const labels =
    locale === "fr"
        ? {
            runtime: "Exécution locale",
            uptime: "Uptime",
            ocr: "OCR",
            llm: "Assistant",
            observationPlayers: "Profils vus",
            observationHands: "Mains observées",
            enabled: "Activé",
            disabled: "Désactivé",
          }
      : {
          runtime: "Exécution locale",
          uptime: "Uptime",
          ocr: "OCR",
          llm: "LLM",
          observationPlayers: "Profiles seen",
          observationHands: "Hands observed",
          enabled: "Enabled",
          disabled: "Disabled",
        };
  const metrics = [
    {
      label: labels.runtime,
      value: payload.runtime.runtime,
      helper: localizeSourceLabel(payload.runtime.status, locale),
    },
    {
      label: labels.uptime,
      value: `${Math.round(payload.runtime.uptimeMs / 1000)}s`,
      helper: payload.transport.source,
    },
    {
      label: labels.ocr,
      value: `${Math.round(payload.ocr.confidence * 100)}%`,
      helper: localizeHistoryEntryLabel(payload.ocr.frameLabel, locale),
    },
    {
      label: labels.llm,
      value: payload.runtime.llm.enabled ? labels.enabled : labels.disabled,
      helper: localizeProviderModeLabel(payload.runtime.llm.providerMode, locale),
    },
  ];
  if (payload.operator.observationModeEnabled || payload.observation.playerCount > 0) {
    metrics.push(
      {
        label: labels.observationPlayers,
        value: String(payload.observation.playerCount),
        helper: payload.observation.backend,
      },
      {
        label: labels.observationHands,
        value: String(payload.observation.observedHands),
        helper: String(payload.observation.handsRecorded),
      }
    );
  }
  return metrics;
}

function isRawRecord(value: unknown): value is RawRecord {
  return typeof value === "object" && value !== null;
}

function asRawRecord(value: unknown): RawRecord {
  return isRawRecord(value) ? value : {};
}

function asRawArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function readRawString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

function readRawNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function readRawStringArray(value: unknown): string[] {
  return asRawArray(value).filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function formatSignedValue(value: number, digits = 1, suffix = ""): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}${suffix}`;
}

function formatRatioPercent(value: number, digits = 0): string {
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(digits)}%`;
}

function readRlAbComparisonRecord(metadata: RawRecord): RawRecord {
  const rlAb = asRawRecord(metadata.rl_ab);
  return asRawRecord(
    rlAb.comparison ?? rlAb.diff ?? metadata.rl_ab_diff ?? metadata.rl_ab_compare ?? metadata.ab_variants ?? rlAb
  );
}

function readRlAbVariant(record: RawRecord, enabled: boolean): RawRecord {
  return enabled
    ? asRawRecord(record.on ?? record.rl_on ?? record.treatment ?? record.b)
    : asRawRecord(record.off ?? record.rl_off ?? record.control ?? record.a);
}

function readRlAbVariantLabel(variant: RawRecord, fallback: string): string {
  return readRawString(
    variant.label ?? variant.name ?? variant.policyLabel ?? variant.policy_label ?? variant.policy ?? variant.variant,
    fallback
  );
}

function buildPolicyPairSummary(spot: RawRecord, decision: RawRecord): Pick<ReplayTimelineSpot, "policyPairKey" | "policyPairLabel"> {
  const decisionMetadata = asRawRecord(decision.metadata);
  const spotMetadata = asRawRecord(spot.metadata);
  const directComparison = readRlAbComparisonRecord(decisionMetadata);
  const comparison =
    Object.keys(directComparison).length > 0 ? directComparison : readRlAbComparisonRecord(spotMetadata);
  const off = readRlAbVariant(comparison, false);
  const on = readRlAbVariant(comparison, true);

  if (Object.keys(off).length === 0 || Object.keys(on).length === 0) {
    return {};
  }

  const offLabel = readRlAbVariantLabel(off, "RL off");
  const onLabel = readRlAbVariantLabel(on, "RL on");
  const policyPairLabel = `${offLabel} vs ${onLabel}`;
  const policyPairKey = `${offLabel.toLowerCase()}__${onLabel.toLowerCase()}`;

  return { policyPairKey, policyPairLabel };
}

function readRlAbSummary(
  spot: RawRecord,
  decision: RawRecord,
  locale: WorkstationLocale
): ReplayTimelineSpot["rlDiffSummary"] | undefined {
  const decisionMetadata = asRawRecord(decision.metadata);
  const spotMetadata = asRawRecord(spot.metadata);
  const directComparison = readRlAbComparisonRecord(decisionMetadata);
  const comparison =
    Object.keys(directComparison).length > 0 ? directComparison : readRlAbComparisonRecord(spotMetadata);
  const off = readRlAbVariant(comparison, false);
  const on = readRlAbVariant(comparison, true);

  if (Object.keys(off).length === 0 || Object.keys(on).length === 0) {
    return undefined;
  }

  const offAction = readRawString(off.chosenAction ?? off.chosen_action ?? off.action, "");
  const onAction = readRawString(on.chosenAction ?? on.chosen_action ?? on.action, "");
  const offEv = readRawNumber(off.heroEv ?? off.hero_ev, NaN);
  const onEv = readRawNumber(on.heroEv ?? on.hero_ev, NaN);
  const offConfidence = readRawNumber(off.confidence, NaN);
  const onConfidence = readRawNumber(on.confidence, NaN);

  const deltaEv =
    Number.isFinite(offEv) && Number.isFinite(onEv)
      ? formatSignedValue(onEv - offEv, 2, " bb")
      : undefined;
  const actionShift =
    offAction && onAction && offAction !== onAction ? `${offAction.replace(/_/g, " ")} -> ${onAction.replace(/_/g, " ")}` : undefined;
  const confidenceShift =
    Number.isFinite(offConfidence) && Number.isFinite(onConfidence) && Math.abs(onConfidence - offConfidence) >= 0.01
      ? `${formatRatioPercent(offConfidence, 0)} -> ${formatRatioPercent(onConfidence, 0)}`
      : undefined;

  if (!deltaEv && !actionShift && !confidenceShift) {
    return undefined;
  }

  return {
    label: locale === "fr" ? "Écart RL" : "RL diff",
    deltaEv,
    actionShift,
    confidenceShift,
  };
}

function parseSignedNumericValue(value: string | undefined): number | null {
  if (!value) {
    return null;
  }
  const match = value.match(/[-+]?\d+(?:[.,]\d+)?/);
  if (!match) {
    return null;
  }
  const numeric = Number(match[0].replace(",", "."));
  return Number.isFinite(numeric) ? numeric : null;
}

function computeReplayImpactScore(spot: ReplayTimelineSpot): number | null {
  const deltaEv = Math.abs(parseSignedNumericValue(spot.rlDiffSummary?.deltaEv) ?? NaN);
  const heroEv = Math.abs(parseSignedNumericValue(spot.heroEv) ?? NaN);
  const exploitability = Math.abs(parseSignedNumericValue(spot.exploitability) ?? NaN);
  const confidence = parseSignedNumericValue(spot.confidence);
  const incidentWeight = Math.min(spot.incidents?.length ?? 0, 3) * 0.75;
  const actionShiftWeight = spot.rlDiffSummary?.actionShift ? 1.5 : 0;
  const confidenceShiftWeight = spot.rlDiffSummary?.confidenceShift ? 0.75 : 0;

  const numericSignals = [deltaEv, heroEv, exploitability].filter((value): value is number => Number.isFinite(value));
  if (numericSignals.length === 0 && incidentWeight === 0 && actionShiftWeight === 0 && confidenceShiftWeight === 0) {
    return null;
  }

  const confidencePenalty = confidence !== null && Number.isFinite(confidence) ? Math.max(0, (100 - confidence) / 100) : 0.15;
  const base =
    (Number.isFinite(deltaEv) ? deltaEv : 0) * 2.25 +
    (Number.isFinite(heroEv) ? heroEv : 0) +
    (Number.isFinite(exploitability) ? exploitability : 0) * 1.5;
  return Number(((base + incidentWeight + actionShiftWeight + confidenceShiftWeight) * (1 + confidencePenalty)).toFixed(2));
}

function attachReplayImpact(spot: ReplayTimelineSpot, locale: WorkstationLocale): ReplayTimelineSpot {
  const impactScore = computeReplayImpactScore(spot);
  return impactScore === null
    ? spot
    : {
        ...spot,
        impactScore,
        impactLabel: locale === "fr" ? "Impact" : "Impact",
      };
}

function buildReplayImpactSummary(
  items: ReplayTimelineSpot[],
  sortedByImpact: boolean,
  locale: WorkstationLocale
): string {
  const impacted = items.filter((item) => typeof item.impactScore === "number");
  if (!sortedByImpact || impacted.length === 0) {
    return locale === "fr"
      ? "Tri chronologique conservé : pas assez de signaux de divergence coûteuse dans le lot courant."
      : "Kept timeline order: not enough costly divergence signal was present in the current bundle.";
  }

  const topSpot = impacted[0];
  const topImpact = typeof topSpot.impactScore === "number" ? topSpot.impactScore.toFixed(topSpot.impactScore >= 10 ? 0 : 1) : "-";
  return locale === "fr"
    ? `${impacted.length} situations triées par impact estimé. Priorité actuelle : ${topSpot.title} (${topImpact}).`
    : `${impacted.length} spots sorted by estimated impact. Current top priority: ${topSpot.title} (${topImpact}).`;
}

function buildReplayReviewQueue(payload: ReplayBridgePayload, locale: WorkstationLocale): {
  items: ReplayTimelineSpot[];
  sortedByImpact: boolean;
  impactSummary: string;
} {
  const baseItems = buildReplayTimelineItems(payload, locale).map((item) => attachReplayImpact(item, locale));
  const impactedItems = baseItems.filter((item) => typeof item.impactScore === "number");
  const sortedByImpact = impactedItems.length >= 2;
  const items = sortedByImpact
    ? [...baseItems].sort((left, right) => {
        const rightImpact = right.impactScore ?? Number.NEGATIVE_INFINITY;
        const leftImpact = left.impactScore ?? Number.NEGATIVE_INFINITY;
        if (rightImpact !== leftImpact) {
          return rightImpact - leftImpact;
        }
        return 0;
      })
    : baseItems;

  return {
    items,
    sortedByImpact,
    impactSummary: buildReplayImpactSummary(items, sortedByImpact, locale),
  };
}

function buildReplayPolicyCompareAggregate(
  items: ReplayTimelineSpot[],
  scopeLabel: string,
  locale: WorkstationLocale
): PolicyCompareAggregate | undefined {
  const comparedSpots = items.filter(
    (item) =>
      item.rlDiffSummary?.deltaEv ||
      item.rlDiffSummary?.actionShift ||
      item.rlDiffSummary?.confidenceShift
  );
  if (comparedSpots.length === 0) {
    return undefined;
  }

  const deltaValues = comparedSpots
    .map((item) => ({ item, value: parseSignedNumericValue(item.rlDiffSummary?.deltaEv) }))
    .filter((entry): entry is { item: ReplayTimelineSpot; value: number } => entry.value !== null && Number.isFinite(entry.value));
  const strongestDelta = deltaValues.reduce<{ item: ReplayTimelineSpot; value: number } | null>((best, current) => {
    if (!best || Math.abs(current.value) > Math.abs(best.value)) {
      return current;
    }
    return best;
  }, null);

  const actionShiftCounts = new Map<string, number>();
  for (const item of comparedSpots) {
    const shift = item.rlDiffSummary?.actionShift;
    if (!shift) {
      continue;
    }
    actionShiftCounts.set(shift, (actionShiftCounts.get(shift) ?? 0) + 1);
  }

  const topActionShiftEntry = Array.from(actionShiftCounts.entries()).sort((left, right) => right[1] - left[1])[0];
  const topSpot = strongestDelta?.item ?? comparedSpots[0];
  const averageDelta =
    deltaValues.length > 0 ? deltaValues.reduce((sum, entry) => sum + entry.value, 0) / deltaValues.length : null;
  const canonicalSpotCounts = new Map<string, number>();
  for (const item of comparedSpots) {
    const key = item.canonicalSpot?.trim();
    if (!key) {
      continue;
    }
    canonicalSpotCounts.set(key, (canonicalSpotCounts.get(key) ?? 0) + 1);
  }
  const dominantCanonicalSpot = Array.from(canonicalSpotCounts.entries()).sort((left, right) => right[1] - left[1])[0];
  const sortedComparisonCandidates = [...comparedSpots]
    .sort((left, right) => {
      const rightScore = Math.abs(parseSignedNumericValue(right.rlDiffSummary?.deltaEv) ?? 0);
      const leftScore = Math.abs(parseSignedNumericValue(left.rlDiffSummary?.deltaEv) ?? 0);
      if (rightScore !== leftScore) {
        return rightScore - leftScore;
      }
      return (right.impactScore ?? 0) - (left.impactScore ?? 0);
    });
  const pairwiseComparisons = sortedComparisonCandidates
    .slice(0, 12)
    .map((item, index) => ({
      id: item.id || `comparison-${index + 1}`,
      title: item.title,
      street: item.street,
      timestamp: item.timestamp,
      policyPairKey: item.policyPairKey,
      policyPairLabel: item.policyPairLabel,
      action: item.action,
      canonicalSpot: item.canonicalSpot,
      gateResult: item.gateResult,
      note: item.note,
      deltaEv: item.rlDiffSummary?.deltaEv,
      actionShift: item.rlDiffSummary?.actionShift,
      confidenceShift: item.rlDiffSummary?.confidenceShift,
      confidence: item.confidence,
      impactScore: item.impactScore,
      impactLabel: item.impactLabel,
    }));
  const comparisonItems = sortedComparisonCandidates
    .slice(0, 4)
    .map((item, index) => ({
      id: item.id || `comparison-${index + 1}`,
      title: item.title,
      street: item.street,
      timestamp: item.timestamp,
      policyPairKey: item.policyPairKey,
      policyPairLabel: item.policyPairLabel,
      action: item.action,
      canonicalSpot: item.canonicalSpot,
      gateResult: item.gateResult,
      note: item.note,
      deltaEv: item.rlDiffSummary?.deltaEv,
      actionShift: item.rlDiffSummary?.actionShift,
      confidenceShift: item.rlDiffSummary?.confidenceShift,
      confidence: item.confidence,
      impactScore: item.impactScore,
      impactLabel: item.impactLabel,
    }));
  const highlightItems = comparedSpots
    .filter((item) => Boolean(item.note || item.rlDiffSummary?.actionShift || item.rlDiffSummary?.confidenceShift))
    .slice(0, 4)
    .map((item, index) => ({
      id: `${item.id || `highlight-${index + 1}`}-highlight`,
      title: item.note || item.title,
      street: item.street,
      timestamp: item.timestamp,
      policyPairKey: item.policyPairKey,
      policyPairLabel: item.policyPairLabel,
      action: item.action,
      canonicalSpot: item.title !== item.note ? item.title : item.canonicalSpot,
      gateResult: item.gateResult,
      note: item.note,
      deltaEv: item.rlDiffSummary?.deltaEv,
      actionShift: item.rlDiffSummary?.actionShift,
      confidenceShift: item.rlDiffSummary?.confidenceShift,
      confidence: item.confidence,
      impactScore: item.impactScore,
      impactLabel: item.impactLabel,
    }));
  const priorityLabels = [
    strongestDelta ? `${locale === "fr" ? "Delta max" : "Largest delta"} ${formatSignedValue(strongestDelta.value, 2, " bb")}` : "",
    topActionShiftEntry ? `${locale === "fr" ? "Shift dominant" : "Common shift"} ${topActionShiftEntry[0]}` : "",
    dominantCanonicalSpot ? `${locale === "fr" ? "Spot repete" : "Repeated spot"} ${dominantCanonicalSpot[0]}` : "",
  ].filter((entry) => entry.length > 0);
  const analysisHints = [
    topActionShiftEntry
      ? locale === "fr"
        ? `Verifier si ${topActionShiftEntry[0]} revient dans plusieurs spots avant d'ouvrir le diff detaille.`
        : `Check whether ${topActionShiftEntry[0]} repeats across multiple spots before opening a full diff.`
      : "",
    dominantCanonicalSpot && dominantCanonicalSpot[1] > 1
      ? locale === "fr"
        ? `Le pattern ${dominantCanonicalSpot[0]} reapparait ${dominantCanonicalSpot[1]} fois dans cette session.`
        : `${dominantCanonicalSpot[0]} appears ${dominantCanonicalSpot[1]} times in this session.`
      : "",
    averageDelta !== null
      ? locale === "fr"
        ? `Le delta moyen ${formatSignedValue(averageDelta, 2, " bb")} aide a distinguer bruit local et tendance session.`
        : `Average delta ${formatSignedValue(averageDelta, 2, " bb")} helps separate local noise from a session trend.`
      : "",
  ].filter((entry) => entry.length > 0).slice(0, 3);
  const coverageSummary =
    locale === "fr"
      ? `${comparedSpots.length} spots compares, ${deltaValues.length} avec delta EV, ${canonicalSpotCounts.size} contextes distincts.`
      : `${comparedSpots.length} comparable spots, ${deltaValues.length} with EV delta, ${canonicalSpotCounts.size} distinct contexts.`;

  return {
    scopeLabel,
    scopeBadge: locale === "fr" ? "Session active" : "Active session",
    sessionLabel: scopeLabel,
    comparedSpots: comparedSpots.length,
    deltaSpots: deltaValues.length,
    actionShiftSpots: comparedSpots.filter((item) => Boolean(item.rlDiffSummary?.actionShift)).length,
    confidenceShiftSpots: comparedSpots.filter((item) => Boolean(item.rlDiffSummary?.confidenceShift)).length,
    distinctContexts: canonicalSpotCounts.size || undefined,
    coverageSummary,
    averageDeltaEv: averageDelta !== null ? formatSignedValue(averageDelta, 2, " bb") : undefined,
    strongestDeltaEv: strongestDelta ? formatSignedValue(strongestDelta.value, 2, " bb") : undefined,
    topActionShift:
      topActionShiftEntry && topActionShiftEntry[1] > 1
        ? `${topActionShiftEntry[0]} · ${topActionShiftEntry[1]}x`
        : topActionShiftEntry?.[0],
    topContext:
      [topSpot.canonicalSpot, topSpot.gateResult].filter(Boolean).join(" · ") ||
      (locale === "fr" ? "Replay courant" : "Current replay"),
    topRecommendation: topSpot.note,
    analysisHints,
    priorityLabels: priorityLabels.slice(0, 3),
    pairwiseComparisons,
    comparisons: comparisonItems,
    highlights: highlightItems,
  };
}

function readRawBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function collectReplayLabels(value: unknown): string[] {
  return asRawArray(value)
    .map((entry) => {
      if (typeof entry === "string") {
        return entry.trim();
      }
      const record = asRawRecord(entry);
      return readRawString(record.label, readRawString(record.id, readRawString(record.message, "")));
    })
    .filter((entry) => entry.length > 0);
}

function readReplayCanonicalSpot(spot: RawRecord, decision: RawRecord): string | undefined {
  const spotMetadata = asRawRecord(spot.metadata);
  const decisionMetadata = asRawRecord(decision.metadata);
  const direct = [
    readRawString(spot.canonical_spot, ""),
    readRawString(decision.canonical_spot, ""),
    readRawString(spotMetadata.canonical_spot, ""),
    readRawString(decisionMetadata.canonical_spot, ""),
    readRawString(spotMetadata.spot_canonical, ""),
    readRawString(decisionMetadata.spot_canonical, ""),
  ].find((value) => value.length > 0);
  if (direct) {
    return direct.replace(/_/g, " ");
  }

  const presetId = readRawString(decisionMetadata.tree_preset_id, readRawString(spotMetadata.tree_preset_id, ""));
  const street = readRawString(spot.street, readRawString(spot.game_stage, ""));
  if (!presetId && !street) {
    return undefined;
  }
  return [presetId || undefined, street || undefined].filter(Boolean).join(" · ");
}

function readReplayGateResult(decision: RawRecord): string | undefined {
  const metadata = asRawRecord(decision.metadata);
  const gate = asRawRecord(decision.gate_decision);
  const allowed =
    typeof gate.allowed === "boolean"
      ? gate.allowed
      : typeof metadata.gate_allowed === "boolean"
        ? metadata.gate_allowed
        : undefined;
  const reason = readRawString(gate.reason, readRawString(metadata.gate_reason, ""));
  const confidence = readRawNumber(gate.confidence, readRawNumber(metadata.gate_confidence, NaN));
  if (allowed == null && !reason && !Number.isFinite(confidence)) {
    return undefined;
  }

  const parts = [allowed == null ? undefined : allowed ? "allow" : "block", reason || undefined];
  if (Number.isFinite(confidence)) {
    parts.push(formatRatioPercent(confidence, 0));
  }
  return parts.filter(Boolean).join(" · ");
}

function readReplayRuntimeMetrics(decision: RawRecord, locale: WorkstationLocale): string[] {
  const metadata = asRawRecord(decision.metadata);
  const metrics = [
    Number.isFinite(readRawNumber(decision.latency_ms, NaN)) ? `${Math.round(readRawNumber(decision.latency_ms, 0))} ms` : "",
    Number.isFinite(readRawNumber(decision.observed_hands, NaN))
      ? `${Math.round(readRawNumber(decision.observed_hands, 0))} ${locale === "fr" ? "mains" : "hands"}`
      : "",
    Number.isFinite(readRawNumber(metadata.observed_hands, NaN))
      ? `${Math.round(readRawNumber(metadata.observed_hands, 0))} ${locale === "fr" ? "mains" : "hands"}`
      : "",
    readRawBoolean(decision.cache_hit) || readRawBoolean(metadata.cache_hit)
      ? locale === "fr"
        ? "cache utilisé"
        : "cache hit"
      : "",
    readRawString(decision.source, "") === "fallback" ? (locale === "fr" ? "secours" : "fallback") : "",
  ].filter((value) => value.length > 0);

  return Array.from(new Set(metrics)).slice(0, 3);
}

function createReplayDetailRows(entries: Array<[label: string, value: string | undefined]>): Array<{ label: string; value: string }> {
  return entries
    .filter((entry): entry is [string, string] => entry[0].trim().length > 0 && typeof entry[1] === "string" && entry[1].trim().length > 0)
    .map(([label, value]) => ({ label, value }));
}

function readReplaySpotDetails(
  spot: RawRecord,
  decision: RawRecord,
  locale: WorkstationLocale
): Array<{ label: string; value: string }> {
  const metadata = asRawRecord(spot.metadata);
  const decisionMetadata = asRawRecord(decision.metadata);
  const labels =
    locale === "fr"
      ? {
          street: "Étape",
          board: "Tableau",
          hero: "Héros",
          pot: "Pot",
          stack: "Tapis",
          preset: "Préréglage",
          actionLine: "Ligne d'action",
        }
      : {
          street: "Street",
          board: "Board",
          hero: "Hero",
          pot: "Pot",
          stack: "Stack",
          preset: "Preset",
          actionLine: "Action line",
        };
  return createReplayDetailRows([
    [labels.street, localizeSourceLabel(readRawString(spot.street, readRawString(spot.game_stage, "")), locale)],
    [labels.board, readRawStringArray(spot.board).join(" ")],
    [labels.hero, readRawString(spot.hero_position, readRawString(metadata.hero_position, ""))],
    [labels.pot, Number.isFinite(readRawNumber(spot.pot_size, NaN)) ? `${readRawNumber(spot.pot_size, 0).toFixed(1)} bb` : readRawString(spot.pot, "")],
    [labels.stack, Number.isFinite(readRawNumber(spot.effective_stack, NaN)) ? `${readRawNumber(spot.effective_stack, 0).toFixed(1)} bb` : ""],
    [labels.preset, readRawString(decisionMetadata.tree_preset_id, readRawString(metadata.tree_preset_id, ""))],
    [labels.actionLine, readRawStringArray(spot.action_history).join(" -> ")],
  ]).slice(0, 6);
}

function readReplayGateDetails(decision: RawRecord, locale: WorkstationLocale): Array<{ label: string; value: string }> {
  const metadata = asRawRecord(decision.metadata);
  const gate = asRawRecord(decision.gate_decision);
  const labels =
    locale === "fr"
      ? {
          decision: "Décision",
          reason: "Raison",
          confidence: "Confiance",
          action: "Action",
          source: "Source",
          latency: "Latence",
          allow: "Autoriser",
          block: "Bloquer",
        }
      : {
          decision: "Decision",
          reason: "Reason",
          confidence: "Confidence",
          action: "Action",
          source: "Source",
          latency: "Latency",
          allow: "Allow",
          block: "Block",
        };
  return createReplayDetailRows([
    [
      labels.decision,
      typeof gate.allowed === "boolean"
        ? gate.allowed
          ? labels.allow
          : labels.block
        : typeof metadata.gate_allowed === "boolean"
          ? metadata.gate_allowed
            ? labels.allow
            : labels.block
          : "",
    ],
    [labels.reason, localizeGateReason(readRawString(gate.reason, readRawString(metadata.gate_reason, "")), locale)],
    [
      labels.confidence,
      Number.isFinite(readRawNumber(gate.confidence, NaN))
        ? formatRatioPercent(readRawNumber(gate.confidence, 0), 0)
        : Number.isFinite(readRawNumber(metadata.gate_confidence, NaN))
          ? formatRatioPercent(readRawNumber(metadata.gate_confidence, 0), 0)
          : "",
    ],
    [labels.action, localizeSourceLabel(readRawString(decision.action, readRawString(decision.chosen_action, "")), locale)],
    [labels.source, localizeSourceLabel(readRawString(decision.source, readRawString(metadata.source, "")), locale)],
    [labels.latency, Number.isFinite(readRawNumber(decision.latency_ms, NaN)) ? `${Math.round(readRawNumber(decision.latency_ms, 0))} ms` : ""],
  ]);
}

function readReplayTraceDetails(decision: RawRecord, locale: WorkstationLocale): Array<{ label: string; value: string }> {
  const metadata = asRawRecord(decision.metadata);
  const traceEntries = asRawArray(decision.decision_trace_history).length > 0
    ? asRawArray(decision.decision_trace_history)
    : asRawArray(metadata.decision_trace_history).length > 0
      ? asRawArray(metadata.decision_trace_history)
      : asRawArray(decision.decision_trace);

  const rows = traceEntries
    .map((entry, index) => {
      if (typeof entry === "string" && entry.trim().length > 0) {
        return { label: `${locale === "fr" ? "Étape" : "Step"} ${index + 1}`, value: entry.trim() };
      }
      const record = asRawRecord(entry);
      const action = readRawString(record.chosen_action, readRawString(record.action, ""));
      const street = readRawString(record.street, "");
      const source = readRawString(record.source, "");
      const confidence = Number.isFinite(readRawNumber(record.confidence, NaN))
        ? formatRatioPercent(readRawNumber(record.confidence, 0), 0)
        : "";
      const value = [
        locale === "fr" ? localizeSourceLabel(action, locale) : action || undefined,
        locale === "fr" ? localizeSourceLabel(street, locale) : street || undefined,
        source ? `via ${localizeSourceLabel(source, locale)}` : undefined,
        confidence ? `${locale === "fr" ? "conf." : "conf"} ${confidence}` : undefined,
      ]
        .filter(Boolean)
        .join(" · ");
      return value ? { label: `${locale === "fr" ? "Étape" : "Step"} ${index + 1}`, value } : null;
    })
    .filter((entry): entry is { label: string; value: string } => entry !== null);

  if (rows.length > 0) {
    return rows.slice(0, 4);
  }

  return createReplayDetailRows([
    [locale === "fr" ? "Incidents" : "Incidents", readReplayIncidents(decision).join(" · ")],
    [locale === "fr" ? "Runtime" : "Runtime", readReplayRuntimeMetrics(decision, locale).join(" · ")],
  ]).slice(0, 3);
}

function readReplayDecisionTrace(decision: RawRecord, locale: WorkstationLocale): string[] {
  const metadata = asRawRecord(decision.metadata);
  const traceEntries = asRawArray(decision.decision_trace_history).length > 0
    ? asRawArray(decision.decision_trace_history)
    : asRawArray(metadata.decision_trace_history).length > 0
      ? asRawArray(metadata.decision_trace_history)
      : asRawArray(decision.decision_trace);

  return traceEntries
    .map((entry) => {
      if (typeof entry === "string") {
        return entry.trim();
      }
      const record = asRawRecord(entry);
      const action = readRawString(record.chosen_action, readRawString(record.action, ""));
      const street = readRawString(record.street, "");
      const source = readRawString(record.source, "");
      return [
        locale === "fr" ? localizeSourceLabel(action, locale) : action || undefined,
        locale === "fr" ? localizeSourceLabel(street, locale) : street || undefined,
        source ? `(${localizeSourceLabel(source, locale)})` : undefined,
      ]
        .filter(Boolean)
        .join(" ");
    })
    .filter((entry) => entry.length > 0)
    .slice(0, 4);
}

function readReplayIncidents(decision: RawRecord): string[] {
  const metadata = asRawRecord(decision.metadata);
  return Array.from(
    new Set([
      ...collectReplayLabels(decision.incidents),
      ...collectReplayLabels(metadata.incidents),
    ])
  ).slice(0, 4);
}

function replaySeverityTone(value: string): SessionLeakGroup["tone"] {
  switch (value) {
    case "critical":
    case "error":
      return "error";
    case "high":
    case "warning":
      return "warning";
    case "success":
      return "success";
    case "info":
      return "info";
    default:
      return "neutral";
  }
}

function getReplaySourceRecord(payload: ReplayBridgePayload): RawRecord {
  const raw = asRawRecord(payload.raw);
  const samples = asRawRecord(raw.samples);
  const replaySample = asRawRecord(samples.replay_analytics);
  return Object.keys(replaySample).length > 0 ? replaySample : raw;
}

function mapReplayPageState(
  payload: ReplayBridgePayload | null,
  isRefreshing: boolean
): ReplayAnalyticsState {
  if (isRefreshing) {
    return "loading";
  }
  if (!payload) {
    return "idle";
  }
  switch (payload.status) {
    case "ready":
      return "ready";
    case "degraded":
      return "degraded";
    case "offline":
      return "offline";
    case "error":
      return "error";
    default:
      return "idle";
  }
}

function buildReplayPageMetrics(payload: ReplayBridgePayload, locale: WorkstationLocale): Metric[] {
  const source = getReplaySourceRecord(payload);
  const sessionCount = Math.max(payload.summary.totalSessions, asRawArray(source.sessions).length, 1);
  const handsIndexed = Math.max(payload.summary.totalHands, readRawNumber(source.hands_indexed, 0));
  const savedSpots = Math.max(payload.summary.analyzedHands, readRawNumber(source.saved_spots, 0));
  const sessionTrend = readRawNumber(source.session_trend_bb, payload.summary.evBbPer100);
  const labels =
    locale === "fr"
      ? {
          sessions: "Sessions",
          sessionsDetail: "Sessions suivies et prêtes à revoir.",
          hands: "Mains indexées",
          handsDetail: "Corpus local consultable.",
          spots: "Spots sauvés",
          spotsDetail: "Réouvrables dans l'atelier du solveur.",
          trend: "Tendance",
          trendDetail: "Dernier delta de session en blindes.",
        }
      : {
          sessions: "Sessions",
          sessionsDetail: "Tracked and ready for review.",
          hands: "Hands indexed",
          handsDetail: "Searchable local replay corpus.",
          spots: "Saved spots",
          spotsDetail: "Promotable into Solver Studio.",
          trend: "Session trend",
          trendDetail: "Latest replay delta in big blinds.",
        };

  return [
    {
      label: labels.sessions,
      value: `${sessionCount}`,
      detail: labels.sessionsDetail,
    },
    {
      label: labels.hands,
      value: `${Math.round(handsIndexed)}`,
      detail: labels.handsDetail,
    },
    {
      label: labels.spots,
      value: `${Math.round(savedSpots)}`,
      detail: labels.spotsDetail,
    },
    {
      label: labels.trend,
      value: formatSignedValue(sessionTrend, 1, " bb"),
      detail: labels.trendDetail,
    },
  ];
}

function buildReplayHeadlineTags(payload: ReplayBridgePayload): string[] {
  const source = getReplaySourceRecord(payload);
  const sessionTags = asRawArray(source.sessions)
    .flatMap((session) => readRawStringArray(asRawRecord(session).tags))
    .slice(0, 4);
  const filterTags = payload.filters.tags.slice(0, 4);
  return [...new Set([...sessionTags, ...filterTags])].slice(0, 6);
}

function buildReplaySessionStats(payload: ReplayBridgePayload, locale: WorkstationLocale): SessionKpi[] {
  const source = getReplaySourceRecord(payload);
  const handsIndexed = Math.max(payload.summary.totalHands, readRawNumber(source.hands_indexed, 0));
  const bestHour = readRawNumber(source.best_hour_bb, payload.summary.totalWinningsBb);
  const labels =
    locale === "fr"
      ? {
          sessions: "Sessions",
          sessionsHelper: "Sessions chargées",
          hands: "Mains indexées",
          handsHelper: "Corpus local consultable",
          reviewed: "Relu",
          reviewedHelper: "Mains déjà envoyées à l’étude",
          bestHour: "Meilleure heure",
          bestHourHelper: "Meilleur bloc rejoué",
        }
      : {
          sessions: "Sessions",
          sessionsHelper: "Loaded replay sessions",
          hands: "Hands indexed",
          handsHelper: "Searchable local hand corpus",
          reviewed: "Reviewed",
          reviewedHelper: "Hands already surfaced for study",
          bestHour: "Best hour",
          bestHourHelper: "Best replay block so far",
        };

  return [
    {
      label: labels.sessions,
      value: `${Math.max(payload.summary.totalSessions, asRawArray(source.sessions).length, 1)}`,
      helper: labels.sessionsHelper,
    },
    {
      label: labels.hands,
      value: `${Math.round(handsIndexed)}`,
      helper: labels.handsHelper,
    },
    {
      label: labels.reviewed,
      value: `${Math.round(payload.summary.analyzedHands)}`,
      helper: labels.reviewedHelper,
    },
    {
      label: labels.bestHour,
      value: formatSignedValue(bestHour, 1, " bb"),
      helper: labels.bestHourHelper,
      tone: bestHour >= 0 ? "success" : "warning",
    },
  ];
}

function buildReplayTrendStats(payload: ReplayBridgePayload, locale: WorkstationLocale): SessionKpi[] {
  const labels =
    locale === "fr"
      ? {
          ev: "EV / 100",
          evHelper: "Tendance de valeur attendue",
          winRate: "Winrate",
          winRateHelper: "Winrate observé",
          latency: "Latence P95",
          latencyHelper: "Latence de replay",
          fallback: "Taux fallback",
          fallbackHelper: "Fréquence du fallback structuré",
        }
      : {
          ev: "EV / 100",
          evHelper: "Expected-value trend",
          winRate: "Win rate",
          winRateHelper: "Observed replay win rate",
          latency: "P95 latency",
          latencyHelper: "Decision replay latency",
          fallback: "Fallback rate",
          fallbackHelper: "Structured fallback frequency",
        };
  return [
    {
      label: labels.ev,
      value: formatSignedValue(payload.summary.evBbPer100, 1, " bb"),
      helper: labels.evHelper,
      tone: payload.summary.evBbPer100 >= 0 ? "success" : "warning",
    },
    {
      label: labels.winRate,
      value: formatSignedValue(payload.summary.winRateBbPer100, 1, " bb"),
      helper: labels.winRateHelper,
      tone: payload.summary.winRateBbPer100 >= 0 ? "success" : "warning",
    },
    {
      label: labels.latency,
      value: `${Math.round(payload.summary.p95LatencyMs)} ms`,
      helper: labels.latencyHelper,
      tone: payload.summary.p95LatencyMs <= 250 ? "success" : "warning",
    },
    {
      label: labels.fallback,
      value: formatRatioPercent(payload.summary.fallbackRate, 1),
      helper: labels.fallbackHelper,
      tone: payload.summary.fallbackRate <= 0.15 ? "success" : "warning",
    },
  ];
}

function buildReplayLeakGroups(payload: ReplayBridgePayload, locale: WorkstationLocale): SessionLeakGroup[] {
  const source = getReplaySourceRecord(payload);
  const leakClusters = asRawArray(source.leak_clusters);
  if (leakClusters.length > 0) {
    return leakClusters.map((cluster, index) => {
      const entry = asRawRecord(cluster);
      const count = readRawNumber(entry.hands, 0);
      return {
        id: readRawString(entry.id, `cluster-${index + 1}`),
        label:
          readRawString(
            entry.label,
            locale === "fr" ? `Cluster leak ${index + 1}` : `Leak cluster ${index + 1}`
          ),
        count,
        detail:
          locale === "fr"
            ? `${count} main${count === 1 ? "" : "s"} taguée${count === 1 ? "" : "s"} dans ce replay.`
            : `${count} tagged hand${count === 1 ? "" : "s"} in the current replay set.`,
        tone: replaySeverityTone(readRawString(entry.severity, "info")),
        tags: [readRawString(entry.id, `cluster-${index + 1}`)].filter(Boolean),
      };
    });
  }

  return payload.highlights.map((highlight) => ({
    id: highlight.id,
    label: highlight.title,
    count: highlight.tags.length,
    detail: highlight.note,
    tone:
      highlight.confidence >= 0.85
        ? "success"
        : highlight.confidence >= 0.7
          ? "info"
          : "warning",
    tags: highlight.tags,
  }));
}

function buildReplayTimelineItems(payload: ReplayBridgePayload, locale: WorkstationLocale = "en"): ReplayTimelineSpot[] {
  const source = getReplaySourceRecord(payload);
  const timeline = asRawArray(source.timeline);

  if (timeline.length > 0) {
    return timeline.map((item, index) => {
      const entry = asRawRecord(item);
      const spot = asRawRecord(entry.spot_snapshot);
      const decision = asRawRecord(entry.decision_snapshot);
      const resultBb = readRawNumber(entry.result_bb, 0);
      const confidence = readRawNumber(decision.confidence, NaN);
      const rlDiffSummary = readRlAbSummary(spot, decision, locale);
      const policyPair = buildPolicyPairSummary(spot, decision);
      return {
        id: readRawString(entry.id, `timeline-${index + 1}`),
        title: readRawString(entry.label, `Replay spot ${index + 1}`),
        street: readRawString(entry.street, readRawString(spot.game_stage, "flop")),
        timestamp: readRawString(entry.created_at, readRawString(source.session_id, payload.refreshedAt)),
        policyPairKey: policyPair.policyPairKey,
        policyPairLabel: policyPair.policyPairLabel,
        action: readRawString(decision.action, "review"),
        result: formatSignedValue(resultBb, 1, " bb"),
        heroEv: Number.isFinite(resultBb) ? formatSignedValue(resultBb, 1, " bb") : undefined,
        canonicalSpot: readReplayCanonicalSpot(spot, decision),
        gateResult: readReplayGateResult(decision),
        runtimeMetrics: readReplayRuntimeMetrics(decision, locale),
        incidents: readReplayIncidents(decision),
        decisionTrace: readReplayDecisionTrace(decision, locale),
        spotDetails: readReplaySpotDetails(spot, decision, locale),
        gateDetails: readReplayGateDetails(decision, locale),
        traceDetails: readReplayTraceDetails(decision, locale),
        rlDiffSummary,
        confidence: Number.isFinite(confidence) ? formatRatioPercent(confidence, 0) : undefined,
        tags: readRawStringArray(entry.tags),
        note: readRawString(entry.recommendedFocus, payload.recommendations[0] ?? ""),
        reviewed: true,
      };
    });
  }

  const replaySpot = asRawRecord(source.replay_spot);
  if (Object.keys(replaySpot).length > 0) {
    const replayDecision = asRawRecord(source.replay_decision);
    const metadata = asRawRecord(replaySpot.metadata);
    const rlDiffSummary = readRlAbSummary(replaySpot, replayDecision, locale);
    const policyPair = buildPolicyPairSummary(replaySpot, replayDecision);
    return [
      {
        id: readRawString(source.selected_session_id, "replay-preview"),
        title: readRawString(metadata.view, "Replay preview").replace(/_/g, " "),
        street: readRawString(replaySpot.street, "flop"),
        timestamp: readRawString(source.selected_session_id, payload.refreshedAt),
        policyPairKey: policyPair.policyPairKey,
        policyPairLabel: policyPair.policyPairLabel,
        action: readRawString(replayDecision.chosen_action, "review"),
        result: formatSignedValue(readRawNumber(replayDecision.hero_ev, 0), 2, " EV"),
        heroEv: formatSignedValue(readRawNumber(replayDecision.hero_ev, 0), 2),
        exploitability: readRawNumber(replayDecision.exploitability, 0).toFixed(2),
        canonicalSpot: readReplayCanonicalSpot(replaySpot, replayDecision),
        gateResult: readReplayGateResult(replayDecision),
        runtimeMetrics: readReplayRuntimeMetrics(replayDecision, locale),
        incidents: readReplayIncidents(replayDecision),
        decisionTrace: readReplayDecisionTrace(replayDecision, locale),
        spotDetails: readReplaySpotDetails(replaySpot, replayDecision, locale),
        gateDetails: readReplayGateDetails(replayDecision, locale),
        traceDetails: readReplayTraceDetails(replayDecision, locale),
        rlDiffSummary,
        tags: readRawStringArray(source.highlights).slice(0, 3),
        note: readRawStringArray(source.notes)[0] ?? payload.notes[0] ?? "",
        reviewed: true,
      },
    ];
  }

  return payload.highlights.map((highlight) => ({
    id: highlight.id,
    title: highlight.title,
    street: highlight.street,
    timestamp: payload.refreshedAt,
    result: highlight.result,
    confidence: formatRatioPercent(highlight.confidence, 0),
    tags: highlight.tags,
    note: highlight.note,
    reviewed: highlight.confidence >= 0.8,
  }));
}

function buildReplaySignals(
  payload: ReplayBridgePayload,
  selectedSpot: ReplayTimelineSpot | undefined,
  locale: WorkstationLocale
): Signal[] {
  const labels =
    locale === "fr"
      ? {
          source: "Source",
          selection: "Sélection",
          selectionWaiting: "En attente",
          selectionNote: "Choisis un nœud pour focaliser la timeline.",
          recommendations: "Recommandations",
          recommendationsNote: "Guidance replay disponible hors ligne.",
          statusPrefix: "Statut replay",
        }
      : {
          source: "Source",
          selection: "Selection",
          selectionWaiting: "Awaiting selection",
          selectionNote: "Pick a replay node to focus the timeline.",
          recommendations: "Recommendations",
          recommendationsNote: "Replay guidance is available offline-safe.",
          statusPrefix: "Replay payload status",
        };
  return [
    {
      label: labels.source,
      value: payload.source,
      note: `${labels.statusPrefix}: ${payload.status}.`,
    },
    {
      label: labels.selection,
      value: selectedSpot?.title ?? labels.selectionWaiting,
      note: selectedSpot?.note ?? labels.selectionNote,
    },
    {
      label: labels.recommendations,
      value: `${payload.recommendations.length}`,
      note: payload.recommendations[0] ?? labels.recommendationsNote,
    },
  ];
}

function buildReplayBundleSections(payload: ReplayBridgePayload, locale: WorkstationLocale): SessionLeakGroup[] {
  const source = getReplaySourceRecord(payload);
  const raw = asRawRecord(payload.raw);
  const sections: SessionLeakGroup[] = [
    {
      id: "summary",
        label: locale === "fr" ? "Résumé" : "Summary",
      count: Object.keys(asRawRecord(source.summary)).length || Object.keys(asRawRecord(raw.summary)).length,
      detail:
        locale === "fr"
          ? `${payload.summary.totalSessions} sessions, ${payload.summary.totalHands} mains, ${payload.summary.analyzedHands} spots relus.`
          : `${payload.summary.totalSessions} sessions, ${payload.summary.totalHands} hands, ${payload.summary.analyzedHands} reviewed spots.`,
      tone: "info",
      tags: [payload.status, payload.source],
    },
    {
      id: "timeline",
      label: locale === "fr" ? "Chronologie" : "Timeline",
      count: buildReplayTimelineItems(payload).length,
      detail:
        locale === "fr"
          ? "Nœuds rejoués disponibles pour revue locale."
          : "Replayed nodes available for local review.",
      tone: "success",
      tags: readRawStringArray(source.highlights).slice(0, 3),
    },
    {
      id: "warnings",
        label: locale === "fr" ? "Alertes" : "Warnings",
      count: payload.warnings.length,
      detail:
        payload.warnings[0] ??
        (locale === "fr" ? "Aucune alerte prioritaire." : "No priority warning attached."),
      tone: payload.warnings.length > 0 ? "warning" : "neutral",
      tags: payload.warnings.slice(0, 2),
    },
    {
      id: "recommendations",
      label: locale === "fr" ? "Recommandations" : "Recommendations",
      count: payload.recommendations.length,
      detail:
        payload.recommendations[0] ??
        (locale === "fr" ? "Aucune recommandation fournie." : "No recommendation was provided."),
      tone: payload.recommendations.length > 0 ? "info" : "neutral",
      tags: payload.recommendations.slice(0, 2),
    },
  ];

  return sections.filter((section) => (section.count ?? 0) > 0 || section.detail.length > 0);
}

function formatReplayImportedAt(value: string, locale: WorkstationLocale): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function resolveReplayBundleImport(
  raw: unknown,
  locale: WorkstationLocale,
  fallbackSessionLabel: string
): ReplayBundleImportResolution {
  const importedReviewPack = readReplayReviewPack(raw);
  if (importedReviewPack) {
    const bundle = createReplayAnalyticsBundleFromReviewPack(importedReviewPack);
    return {
      payload: hydrateReplayAnalyticsPayloadFromBundle(bundle),
      importedAt: importedReviewPack.exportedAt,
      sessionLabel: importedReviewPack.sessionLabel ?? fallbackSessionLabel,
      selectedSpotId:
        importedReviewPack.currentReplay?.selectedSpotId ?? importedReviewPack.currentReplay?.selectedSpot?.id,
      statusMessage:
        importedReviewPack.currentReplay?.selectedSpot?.note ??
        importedReviewPack.recommendations?.[0] ??
        importedReviewPack.notes?.[0],
    };
  }

  return {
    payload: hydrateReplayAnalyticsPayloadFromBundle(raw),
    importedAt: new Date().toISOString(),
  };
}

function buildReplayPolicyCompareSelectedSpot(spot: ReplayTimelineSpot | undefined): ReplayPolicyCompareSpotSnapshot | undefined {
  if (!spot) {
    return undefined;
  }

    return {
      id: spot.id,
      title: spot.title,
      street: spot.street,
      timestamp: spot.timestamp,
      policyPairKey: spot.policyPairKey,
      policyPairLabel: spot.policyPairLabel,
      action: spot.action,
    canonicalSpot: spot.canonicalSpot,
    gateResult: spot.gateResult,
    note: spot.note,
    deltaEv: spot.rlDiffSummary?.deltaEv,
    actionShift: spot.rlDiffSummary?.actionShift,
    confidenceShift: spot.rlDiffSummary?.confidenceShift,
    confidence: spot.confidence,
    impactScore: spot.impactScore,
    impactLabel: spot.impactLabel,
  };
}

function buildReplayReviewPackSpot(spot: ReplayTimelineSpot | undefined, selected = false) {
  if (!spot) {
    return undefined;
  }

  return {
    id: spot.id,
    title: spot.title,
    street: spot.street,
    timestamp: spot.timestamp,
    policyPairKey: spot.policyPairKey,
    policyPairLabel: spot.policyPairLabel,
    action: spot.action,
    result: spot.result,
    heroEv: spot.heroEv,
    exploitability: spot.exploitability,
    confidence: spot.confidence,
    canonicalSpot: spot.canonicalSpot,
    gateResult: spot.gateResult,
    note: spot.note,
    tags: spot.tags,
    runtimeMetrics: spot.runtimeMetrics,
    incidents: spot.incidents,
    decisionTrace: spot.decisionTrace,
    spotDetails: spot.spotDetails,
    gateDetails: spot.gateDetails,
    traceDetails: spot.traceDetails,
    deltaEv: spot.rlDiffSummary?.deltaEv,
    actionShift: spot.rlDiffSummary?.actionShift,
    confidenceShift: spot.rlDiffSummary?.confidenceShift,
    impactScore: spot.impactScore,
    impactLabel: spot.impactLabel,
    reviewed: spot.reviewed,
    selected,
  };
}

function downloadJsonFile(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  window.URL.revokeObjectURL(objectUrl);
}

function sanitizeFileNameSegment(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48) || "session"
  );
}

function getConfigSourceRecord(payload: ConfigBridgePayload): RawRecord {
  const raw = asRawRecord(payload.raw);
  const samples = asRawRecord(raw.samples);
  const configSample = asRawRecord(samples.config_lab);
  return Object.keys(configSample).length > 0 ? configSample : raw;
}

function normalizePresetPackState(status: string, recommended = false): PresetPackState {
  if (status === "active") {
    return "active";
  }
  if (status === "beta") {
    return "beta";
  }
  if (status === "locked") {
    return "locked";
  }
  return recommended ? "active" : "ready";
}

function buildConfigPresetItems(payload: ConfigBridgePayload, locale: WorkstationLocale): PresetPackItem[] {
  const source = getConfigSourceRecord(payload);
  const rawPresets = asRawArray(source.available_presets);
  if (rawPresets.length > 0) {
    return rawPresets.map((preset, index) => {
      const entry = asRawRecord(preset);
      const playerCount = readRawNumber(entry.player_count, payload.solver.availablePresetIds.length > 0 ? 2 : 0);
      const presetId = readRawString(entry.preset_id, readRawString(entry.id, `preset-${index + 1}`));
      return {
        id: presetId,
        name: readRawString(entry.title, readRawString(entry.label, presetId)),
        description: readRawString(
          entry.description,
          locale === "fr" ? "Préréglage solveur disponible localement." : "Locally available solver preset."
        ),
        status: normalizePresetPackState(readRawString(entry.status), Boolean(entry.recommended)),
        tag: readRawString(entry.street_focus, "solver"),
        coverage: playerCount > 0 ? `${playerCount} ${locale === "fr" ? "joueurs" : "players"}` : locale === "fr" ? "Heads-up" : "Heads-up",
        memoryFootprint: readRawString(entry.memory_mode, locale === "fr" ? "équilibré" : "balanced"),
        solveTime: `${payload.solver.timeBudgetMs} ms ${locale === "fr" ? "budget" : "budget"}`,
      };
    });
  }

  const presetPacks = asRawArray(source.preset_packs);
  if (presetPacks.length > 0) {
    return presetPacks.map((preset, index) => {
      const entry = asRawRecord(preset);
      const presetId = readRawString(entry.id, `preset-pack-${index + 1}`);
      return {
        id: presetId,
        name: readRawString(entry.label, presetId),
        description: `${locale === "fr" ? "Famille" : "Preset family"} · ${readRawString(entry.family, locale === "fr" ? "personnalisé" : "custom")}`,
        status: normalizePresetPackState(readRawString(entry.status), true),
        tag: readRawString(entry.family, "custom"),
        coverage: locale === "fr" ? "Pack" : "Pack",
        memoryFootprint: locale === "fr" ? "équilibré" : "balanced",
        solveTime: `${payload.solver.timeBudgetMs} ms ${locale === "fr" ? "budget" : "budget"}`,
      };
    });
  }

  return payload.solver.availablePresetIds.map((presetId) => ({
    id: presetId,
    name: presetId.replace(/_/g, " "),
    description:
      locale === "fr"
        ? "Disponible depuis la configuration solver V2 normalisée."
        : "Available from the normalized V2 solver configuration.",
    status: presetId === payload.solver.selectedPresetId ? "active" : "ready",
    tag: locale === "fr" ? "normalisé" : "normalized",
    coverage: `${payload.solver.availablePresetIds.length} ${locale === "fr" ? "presets" : "presets"}`,
    memoryFootprint: payload.solver.treeCompression,
    solveTime: `${payload.solver.timeBudgetMs} ms ${locale === "fr" ? "budget" : "budget"}`,
  }));
}

function buildConfigPageMetrics(
  payload: ConfigBridgePayload,
  activePresetId: string,
  locale: WorkstationLocale
): Metric[] {
  const labels =
    locale === "fr"
      ? {
          preset: "Préréglage",
          presetDetail: "Profil d’étude courant.",
          runtime: "Exécution locale",
          benchmarks: "Mesures",
          benchmarksDetail: "Entrées de validation visibles.",
          copilot: "Assistant",
          enabled: "Activé",
          disabled: "Désactivé",
        }
      : {
          preset: "Preset",
          presetDetail: "Current study profile selection.",
          runtime: "Runtime",
          benchmarks: "Benchmarks",
          benchmarksDetail: "Validation and lab entries currently visible.",
          copilot: "Copilot",
          enabled: "Enabled",
          disabled: "Disabled",
        };
  return [
    {
      label: labels.preset,
      value: activePresetId || payload.solver.selectedPresetId,
      detail: labels.presetDetail,
    },
    {
      label: labels.runtime,
      value: payload.runtime.transport,
      detail: localizeSourceLabel(payload.source, locale),
    },
    {
      label: labels.benchmarks,
      value: `${payload.benchmarks.length}`,
      detail: labels.benchmarksDetail,
    },
    {
      label: labels.copilot,
      value: payload.llm.enabled ? labels.enabled : labels.disabled,
      detail: localizePrivacyModeLabel(payload.llm.privacyMode, locale),
    },
  ];
}

function buildConfigBackendItems(payload: ConfigBridgePayload, locale: WorkstationLocale): string[] {
  const source = getConfigSourceRecord(payload);
  const rawBackends = asRawArray(source.backends);
  if (rawBackends.length > 0) {
    return rawBackends.map((backend) => {
      const entry = asRawRecord(backend);
        return `${readRawString(entry.label, locale === "fr" ? "Service" : "Backend")} · ${
          Boolean(entry.ready) ? (locale === "fr" ? "prêt" : "ready") : locale === "fr" ? "hors ligne" : "offline"
        } · ${readRawString(entry.kind, locale === "fr" ? "général" : "general")}`;
      });
    }

  return [
    locale === "fr" ? `Transport d'exécution locale · ${payload.runtime.transport}` : `Runtime transport · ${payload.runtime.transport}`,
    locale === "fr"
      ? `Préréglage solveur principal · ${payload.solver.selectedPresetId}`
      : `Primary solver preset · ${payload.solver.selectedPresetId}`,
    locale === "fr"
      ? `Cache · ${payload.solver.cacheEnabled ? "activé" : "désactivé"}`
      : `Cache · ${payload.solver.cacheEnabled ? "enabled" : "disabled"}`,
  ];
}

function buildConfigBenchmarkItems(payload: ConfigBridgePayload): string[] {
  const source = getConfigSourceRecord(payload);
  const rawStats = asRawArray(source.benchmark_stats);
  if (rawStats.length > 0) {
    return rawStats.map((stat) => {
      const entry = asRawRecord(stat);
      const unit = readRawString(entry.unit, "");
      const target = typeof entry.target === "number" ? ` · target ${entry.target}${unit ? ` ${unit}` : ""}` : "";
      return `${readRawString(entry.name, "benchmark")} · ${readRawNumber(entry.value, 0)}${unit ? ` ${unit}` : ""}${target}`;
    });
  }

  return payload.benchmarks.map((benchmark) => {
    const scoreLabel = benchmark.score > 0 ? ` · score ${benchmark.score.toFixed(2)}` : "";
    return `${benchmark.name} · ${benchmark.status}${scoreLabel}`;
  });
}

function buildConfigSignals(
  payload: ConfigBridgePayload,
  activePresetId: string,
  locale: WorkstationLocale
): Signal[] {
  const labels =
    locale === "fr"
      ? {
          provider: "Fournisseur",
          providerEnabled: "L’assistant optionnel reste hors du chemin live.",
          providerDisabled: "L’assistant optionnel est désactivé.",
          privacy: "Confidentialité",
          privacyNote: "La confidentialité reste explicite et contrôlée.",
          activePreset: "Préréglage actif",
          presetsAvailable: (count: number) => `${count} préréglage(s) disponibles dans le payload courant.`,
        }
      : {
          provider: "Provider",
          providerEnabled: "The optional copilot remains outside the live decision path.",
          providerDisabled: "The optional copilot is currently disabled.",
          privacy: "Privacy",
          privacyNote: "Privacy stays explicit and operator-controlled.",
          activePreset: "Active preset",
          presetsAvailable: (count: number) => `${count} preset(s) available in the current payload.`,
        };
  return [
    {
      label: labels.provider,
      value: localizeProviderModeLabel(payload.llm.providerMode, locale),
      note: payload.llm.enabled
        ? labels.providerEnabled
        : labels.providerDisabled,
    },
    {
      label: labels.privacy,
      value: localizePrivacyModeLabel(payload.llm.privacyMode, locale),
      note: payload.warnings[0] ?? labels.privacyNote,
    },
    {
      label: labels.activePreset,
      value: activePresetId || payload.solver.selectedPresetId,
      note: labels.presetsAvailable(payload.solver.availablePresetIds.length),
    },
  ];
}

function describeSolverStudioResult(
  result: SolverStudioSolveResult,
  locale: WorkstationLocale
) {
  const source = result.transport.source;
  if (locale === "fr") {
    switch (result.status) {
      case "success":
        return `Calcul terminé via ${localizeSourceLabel(source, locale)}.`;
      case "fallback":
        return `Calcul terminé avec secours via ${localizeSourceLabel(source, locale)}.`;
      case "offline":
        return "Solver local hors ligne.";
      case "error":
      default:
        return `Échec du calcul via ${localizeSourceLabel(source, locale)}.`;
    }
  }

  switch (result.status) {
    case "success":
      return `Solve completed via ${source}.`;
    case "fallback":
      return `Solve completed with fallback via ${source}.`;
    case "offline":
      return "Local solver is offline.";
    case "error":
    default:
      return `Solve failed via ${source}.`;
  }
}

function describeBotCockpitPayload(payload: BotCockpitPayload, locale: WorkstationLocale) {
  const runtime = payload.runtime.runtime;
  const operatorStatus = payload.operator.status;
  const assisted = asRawRecord(payload.decision.metadata.assisted);
  const assistedReason = readRawString(assisted.reason, "manual_review_required");
  const assistedReady = typeof assisted.auto_execute === "boolean" ? assisted.auto_execute : false;
  if (locale === "fr") {
    if (operatorStatus === "paused") {
      return "Capture live en pause pour revue opérateur.";
    }
    if (operatorStatus === "manual_override") {
      return "Override manuel actif. L’opérateur garde la main sur l’exécution.";
    }
    if (operatorStatus === "assisted" || payload.operator.assistedModeEnabled) {
      if (assistedReady) {
        return "Mode assisté actif. Confiance suffisante: le bot clique lui-même quand l’action est prête.";
      }
      if (assistedReason === "insufficient_profile_data") {
        return "Mode assisté actif. Pas encore assez de données adverses fiables: clique toi-même pour cette décision.";
      }
      if (assistedReason === "low_state_confidence") {
        return "Mode assisté actif. La lecture écran est encore trop incertaine: clique toi-même.";
      }
      if (assistedReason === "low_gate_confidence" || assistedReason === "gate_blocked") {
        return "Mode assisté actif. La sécurité bloque ou doute encore du spot: clique toi-même.";
      }
      if (assistedReason === "solver_fallback") {
        return "Mode assisté actif. Le solver est en mode repli sur ce spot: clique toi-même.";
      }
      if (assistedReason === "low_decision_confidence") {
        return "Mode assisté actif. La décision n’est pas encore assez fiable: clique toi-même.";
      }
      return "Mode assisté actif. Le bot continue d’apprendre en live, mais il attend ton clic pour ce spot.";
    }
    if (operatorStatus === "observation") {
      return `Mode observation actif. ${payload.observation.playerCount} profils et ${payload.observation.observedHands} mains observées.`;
    }
    if (operatorStatus === "shadow") {
      return "Mode shadow actif. Le runtime observe sans exécuter d’action automatique.";
    }
    switch (payload.state) {
      case "live":
        return `Cockpit du bot actif sur ${runtime}.`;
      case "degraded":
        return `Cockpit du bot dégradé via ${payload.transport.source}, exécution locale encore disponible.`;
      case "offline":
        return "Le cockpit du bot fonctionne en mode local de secours.";
      default:
        return "Données du cockpit du bot chargées.";
    }
  }

  if (operatorStatus === "paused") {
    return "Live capture is paused for operator review.";
  }
  if (operatorStatus === "manual_override") {
    return "Manual override is active. The operator keeps control of execution.";
  }
  if (operatorStatus === "assisted" || payload.operator.assistedModeEnabled) {
    if (assistedReady) {
      return "Assisted mode is active. Confidence is high enough, so the bot can click on its own.";
    }
    if (assistedReason === "insufficient_profile_data") {
      return "Assisted mode is active. There is not enough reliable opponent data yet, so you should click this spot yourself.";
    }
    if (assistedReason === "low_state_confidence") {
      return "Assisted mode is active. Screen reading is still too uncertain, so you should click yourself.";
    }
    if (assistedReason === "low_gate_confidence" || assistedReason === "gate_blocked") {
      return "Assisted mode is active. The safety gate is still blocking or doubting this spot, so you should click yourself.";
    }
    if (assistedReason === "solver_fallback") {
      return "Assisted mode is active. The solver is falling back on this spot, so you should click yourself.";
    }
    if (assistedReason === "low_decision_confidence") {
      return "Assisted mode is active. The decision is still not reliable enough, so you should click yourself.";
    }
    return "Assisted mode is active. The bot keeps learning live, but it is still waiting for you to click this spot.";
  }
  if (operatorStatus === "observation") {
    return `Observation mode is active. ${payload.observation.playerCount} profiles and ${payload.observation.observedHands} hands observed.`;
  }
  if (operatorStatus === "shadow") {
    return "Shadow mode is active. The runtime stays observational without auto-executing.";
  }
  switch (payload.state) {
    case "live":
      return `Bot Cockpit live on ${runtime}.`;
    case "degraded":
      return `Bot Cockpit degraded via ${payload.transport.source}; runtime still available.`;
    case "offline":
      return "Bot Cockpit is running in offline-safe fallback mode.";
    default:
      return "Bot Cockpit payload loaded.";
  }
}

function describeReplayPayload(payload: ReplayBridgePayload, locale: WorkstationLocale) {
  if (locale === "fr") {
    switch (payload.status) {
      case "ready":
        return `Replay prêt via ${payload.source}.`;
      case "degraded":
        return `Replay partiel via ${payload.source}.`;
      case "offline":
        return "Replay en mode local hors ligne.";
      case "error":
        return "Le chargement replay a échoué.";
      default:
        return "Replay en attente.";
    }
  }

  switch (payload.status) {
    case "ready":
      return `Replay ready via ${payload.source}.`;
    case "degraded":
      return `Replay partially loaded via ${payload.source}.`;
    case "offline":
      return "Replay is running in offline-safe mode.";
    case "error":
      return "Replay loading failed.";
    default:
      return "Replay is waiting for data.";
  }
}

function describeConfigPayload(payload: ConfigBridgePayload, locale: WorkstationLocale) {
  if (locale === "fr") {
    switch (payload.status) {
      case "ready":
        return `Configuration & Labo prêt via ${payload.source}.`;
      case "degraded":
        return `Configuration & Labo partiel via ${payload.source}.`;
      case "offline":
        return "Configuration & Labo reste en mode local hors ligne.";
      case "error":
      default:
        return "Le chargement de Configuration & Labo a échoué.";
    }
  }

  switch (payload.status) {
    case "ready":
      return `Config & Lab ready via ${payload.source}.`;
    case "degraded":
      return `Config & Lab partially loaded via ${payload.source}.`;
    case "offline":
      return "Config & Lab is running in offline-safe mode.";
    case "error":
    default:
      return "Config & Lab loading failed.";
  }
}

function mapConfigRuntimeState(
  payload: ConfigBridgePayload | null,
  isRefreshing: boolean
): RuntimeReadinessState {
  if (isRefreshing) {
    return "checking";
  }
  if (!payload) {
    return "offline";
  }
  if (payload.status === "ready") {
    return "ready";
  }
  if (payload.status === "degraded") {
    return "degraded";
  }
  return "offline";
}

function mapConfigPrivacyMode(mode: ConfigBridgePrivacyMode): ConfigLabPrivacySelection {
  return mode;
}

function normalizeConfigRolesEnabled(roles: string[]): UiLlmConfig["rolesEnabled"] {
  const normalized = roles.map((role) => role.toLowerCase());
  return {
    analysis: normalized.some(
      (role) =>
        role.includes("analysis") ||
        role.includes("spot") ||
        role.includes("line") ||
        role.includes("decision")
    ),
    operator_assistance: normalized.some(
      (role) =>
        role.includes("operator") ||
        role.includes("assist") ||
        role.includes("ocr") ||
        role.includes("fallback")
    ),
    strategy_coach: normalized.some((role) => role.includes("strategy")),
    replay_review: normalized.some(
      (role) => role.includes("replay") || role.includes("session")
    ),
  };
}

function normalizeConfigScopesEnabled(scopes: string[]): UiLlmConfig["contextScopesEnabled"] {
  const normalized = scopes.map((scope) => scope.toLowerCase());
  return {
    spot: normalized.some((scope) => scope.includes("spot")),
    decision: normalized.some((scope) => scope.includes("decision")),
    replay: normalized.some((scope) => scope.includes("replay")),
    runtime: normalized.some((scope) => scope.includes("runtime")),
    ocr: normalized.some((scope) => scope.includes("ocr")),
    settings: normalized.some(
      (scope) => scope.includes("config") || scope.includes("setting")
    ),
    fallback: normalized.some((scope) => scope.includes("fallback")),
  };
}

function toPersistableConfigLabLlm(
  payload: ConfigBridgePayload,
  overrides: Partial<UiLlmConfig> = {}
): UiLlmConfig {
  return createDefaultLlmConfig({
    enabled: payload.llm.enabled,
    providerMode: payload.llm.providerMode,
    baseUrl: payload.llm.baseUrl,
    apiKeyRef: payload.llm.apiKeyRef,
    model: payload.llm.model,
    temperature: payload.llm.temperature,
    maxOutputTokens: payload.llm.maxOutputTokens,
    streaming: payload.llm.streaming,
    privacyMode: payload.llm.privacyMode,
    rolesEnabled: normalizeConfigRolesEnabled(payload.llm.rolesEnabled),
    contextScopesEnabled: normalizeConfigScopesEnabled(payload.llm.contextScopesEnabled),
    ...overrides,
  });
}

function applyPersistedConfigLabLlm(
  payload: ConfigBridgePayload,
  config: UiLlmConfig
): ConfigBridgePayload {
  return {
    ...payload,
    llm: {
      ...payload.llm,
      enabled: config.enabled,
      providerMode: config.providerMode,
      baseUrl: config.baseUrl,
      apiKeyRef: config.apiKeyRef,
      model: config.model,
      temperature: config.temperature,
      maxOutputTokens: config.maxOutputTokens,
      streaming: config.streaming,
      privacyMode: config.privacyMode,
      rolesEnabled: Object.entries(config.rolesEnabled)
        .filter(([, enabled]) => enabled)
        .map(([role]) => role),
      contextScopesEnabled: Object.entries(config.contextScopesEnabled)
        .filter(([, enabled]) => enabled)
        .map(([scope]) => scope),
    },
    privacy: {
      strictLocal: config.privacyMode === "strict_local",
      redactedRemote: config.privacyMode === "redacted_remote",
      fullRemote: config.privacyMode === "full_remote",
    },
  };
}

async function persistConfigLabOcr(config: ConfigBridgePayload["ocr"]): Promise<ConfigBridgePayload["ocr"]> {
  return persistStoredOcrConfig(config);
}

async function getConfigLabOcrStatus(): Promise<ConfigLabOcrStatus | null> {
  const globalWindow = globalThis as typeof globalThis & {
    __TAURI__?: {
      core?: { invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown> };
      invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
    };
  };

  let invoke = globalWindow.__TAURI__?.core?.invoke ?? globalWindow.__TAURI__?.invoke ?? null;
  if (!invoke) {
    try {
      const core = await import("@tauri-apps/api/core");
      invoke = typeof core.invoke === "function" ? core.invoke : null;
    } catch {
      return null;
    }
  }

  const response = (await invoke("get_ocr_status")) as Record<string, unknown>;
  return {
    supportedEngines: Array.isArray(response.supported_engines)
      ? response.supported_engines.filter((value): value is string => typeof value === "string")
      : [],
    requestedEngines: Array.isArray(response.requested_engines)
      ? response.requested_engines.filter((value): value is string => typeof value === "string")
      : [],
    loadedEngines: Array.isArray(response.loaded_engines)
      ? response.loaded_engines.filter((value): value is string => typeof value === "string")
      : [],
    unavailableEngines:
      typeof response.unavailable_engines === "object" && response.unavailable_engines !== null
        ? (response.unavailable_engines as Record<string, string>)
        : {},
    mode: (typeof response.mode === "string" ? response.mode : "consensus_amounts") as ConfigLabOcrMode,
    parallel: typeof response.parallel === "boolean" ? response.parallel : true,
    useGpu: typeof response.use_gpu === "boolean" ? response.use_gpu : true,
  };
}

async function runConfigLabOcrProbe(args: {
  imageName: string;
  imageBase64: string;
  field: "text" | "amount";
  engines: string[];
  mode: ConfigLabOcrMode;
  parallel: boolean;
}) {
  const globalWindow = globalThis as typeof globalThis & {
    __TAURI__?: {
      core?: { invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown> };
      invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
    };
  };
  let invoke = globalWindow.__TAURI__?.core?.invoke ?? globalWindow.__TAURI__?.invoke ?? null;
  if (!invoke) {
    const core = await import("@tauri-apps/api/core");
    invoke = typeof core.invoke === "function" ? core.invoke : null;
  }
  if (!invoke) {
    throw new Error("Tauri host unavailable");
  }
  return invoke("run_ocr_probe", {
    request: {
      image_name: args.imageName,
      image_base64: args.imageBase64,
      field: args.field,
      engines: args.engines,
      mode: args.mode,
      parallel: args.parallel,
    },
  });
}

function SurfaceSidebar({
  onNavigate,
  signals,
}: {
  onNavigate?: () => void;
  signals: Signal[];
}) {
  const { copy } = useWorkstationI18n();
  return (
    <nav className="surface-sidebar" aria-label="Primary">
      <div className="brand-block">
        <div className="brand-mark">PM</div>
        <div>
          <strong>PokerMaster</strong>
          <span>{copy.brandSubtitle}</span>
        </div>
      </div>

      <div className="sidebar-section">
        <span className="sidebar-section__label">{copy.navigation}</span>
        <div className="sidebar-links">
          {surfaces.map((surface, index) => {
            const surfaceText = getSurfaceText(surface, copy);
            return (
              <NavLink
                key={surface.path}
                to={surface.path}
                className={({ isActive }) =>
                  `sidebar-link ${isActive ? "sidebar-link--active" : ""}`
                }
                onClick={onNavigate}
              >
                <span className={`sidebar-link__mark sidebar-link__mark--${surface.accent}`}>
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="sidebar-link__copy">
                  <strong>{surfaceText.label}</strong>
                </span>
              </NavLink>
            );
          })}
        </div>
      </div>

      <div className="sidebar-section sidebar-section--status">
        <span className="sidebar-section__label">{copy.runtime}</span>
        <div className="runtime-stack">
          {signals.map((signal) => (
            <div key={signal.label} className="runtime-row">
              <span>{signal.label}</span>
              <strong>{signal.value}</strong>
            </div>
          ))}
        </div>
      </div>
    </nav>
  );
}

export function WorkstationShell() {
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<RuntimeSnapshot | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [locale, setLocale] = useState<WorkstationLocale>(() => {
    if (typeof window === "undefined") {
      return "fr";
    }
    const stored = window.localStorage.getItem(WORKSTATION_LOCALE_STORAGE_KEY);
    return stored === "en" || stored === "fr" ? stored : "fr";
  });
  const copy = useMemo(() => getWorkstationCopy(locale), [locale]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(WORKSTATION_LOCALE_STORAGE_KEY, locale);
    }
  }, [locale]);

  useEffect(() => {
    let isActive = true;
    const refreshRuntimeSnapshot = () => {
      loadRuntimeSnapshot()
        .then((snapshot) => {
          if (isActive) {
            setRuntimeSnapshot(snapshot);
            setRuntimeError(snapshot.status === "offline" ? copy.runtimeError : null);
          }
        })
        .catch((error) => {
          if (isActive) {
            setRuntimeError(
              error instanceof Error
                ? error.message
                : locale === "fr"
                  ? "Impossible de charger le snapshot runtime"
                  : "Unable to load runtime snapshot"
            );
          }
        });
    };
    const handleLlmConfigUpdated = () => {
      refreshRuntimeSnapshot();
    };

    refreshRuntimeSnapshot();
    if (typeof window !== "undefined") {
      window.addEventListener(LLM_CONFIG_UPDATED_EVENT, handleLlmConfigUpdated);
    }

    return () => {
      isActive = false;
      if (typeof window !== "undefined") {
        window.removeEventListener(LLM_CONFIG_UPDATED_EVENT, handleLlmConfigUpdated);
      }
    };
  }, [copy.runtimeError, locale]);

  const runtimeSignals = buildRuntimeSignals(runtimeSnapshot, runtimeError, copy);
  const initialTask = taskForSurface(location.pathname);

  return (
    <WorkstationI18nContext.Provider value={{ locale, setLocale, copy }}>
      <div className="app-shell">
        <div className={`mobile-overlay ${mobileNavOpen ? "mobile-overlay--open" : ""}`}>
          <div className="mobile-overlay__panel">
            <button
              type="button"
              className="mobile-overlay__close"
              onClick={() => setMobileNavOpen(false)}
              aria-label={locale === "fr" ? "Fermer la navigation" : "Close navigation"}
            >
              {locale === "fr" ? "Fermer" : "Close"}
            </button>
            <SurfaceSidebar signals={runtimeSignals} onNavigate={() => setMobileNavOpen(false)} />
          </div>
        </div>

        <aside className="app-sidebar">
          <SurfaceSidebar signals={runtimeSignals} />
        </aside>

        <div className="app-workspace">
          <button
            type="button"
            className="mobile-nav-toggle"
            onClick={() => setMobileNavOpen(true)}
            aria-label={locale === "fr" ? "Ouvrir la navigation" : "Open navigation"}
          >
            {locale === "fr" ? "Menu" : "Menu"}
          </button>

          <main className="workspace-main">
            <Outlet />
          </main>

          <section className="workspace-support">
            <LlmDock
              runtime={runtimeSnapshot}
              runtimeError={runtimeError}
              initialTask={initialTask}
            />
          </section>
        </div>
      </div>
    </WorkstationI18nContext.Provider>
  );
}

export function SolverStudioPage() {
  const { locale, copy } = useWorkstationI18n();
  const text = useWorkstationText(locale);
  const studio = text.t((c) => c.solverStudio);
  const common = text.t((c) => c.common);
  const initialSamples = getSolverStudioSampleSpots();
  const initialSample = initialSamples[0] ?? {
    id: "default",
    title: locale === "fr" ? "Cas simple par défaut" : "Default simple case",
    description:
      locale === "fr"
        ? "Exemple local de secours pour lancer un calcul simple."
        : "Fallback local example for a simple solve.",
    request: {
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
    },
  };
  const [sampleSpots, setSampleSpots] = useState<SolverStudioSpotPreset[]>(initialSamples);
  const [selectedSample, setSelectedSample] = useState<SolverStudioSpotPreset | null>(initialSample);
  const [selectedSampleId, setSelectedSampleId] = useState(initialSample.id);
  const [builderDraft, setBuilderDraft] = useState<SpotBuilderDraft>(() =>
    createSpotBuilderDraftFromPreset(initialSample)
  );
  const [solveResult, setSolveResult] = useState<SolverStudioSolveResult | null>(null);
  const [solveHistory, setSolveHistory] = useState<CachedSolveEntry[]>([]);
  const [isSolving, setIsSolving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>(studio.loadInstruction);

  useEffect(() => {
    let isActive = true;
    const capturedPreset = loadCapturedCockpitPreset(locale);

    if (capturedPreset) {
      setSampleSpots((currentSamples) => {
        const merged = currentSamples.filter((sample) => sample.id !== capturedPreset.id);
        return [capturedPreset, ...merged];
      });
    }

    loadSolverStudioDefaultSpot()
      .then((preset) => {
        if (!isActive) {
          return;
        }

        setSampleSpots((currentSamples) => {
          const merged = currentSamples.filter((sample) => sample.id !== preset.id);
          return [preset, ...merged];
        });
        setSelectedSample(preset);
        setSelectedSampleId(preset.id);
        setBuilderDraft(createSpotBuilderDraftFromPreset(preset));
        setSolveResult(null);
        setStatusMessage(studio.loadedDefault(preset.title));
      })
      .catch(() => {
        if (isActive) {
          setStatusMessage(studio.usingBundledSamples);
        }
      });

    return () => {
      isActive = false;
    };
  }, [copy, locale]);

  const presetOptions = listSolverTreePresets().map((preset) => ({
    value: preset.id,
    label: preset.label,
    description: preset.description,
  }));
  const studioDraft = createStudioDraftFromForm(builderDraft, selectedSample, locale);
  const draftBuild = buildSolverStudioRequest(studioDraft, createDefaultStudioSpot());
  const currentSpot = draftBuild.spot;
  const resultState = mapSolveResultToPanelState(solveResult, isSolving);
  const studioMetrics = buildStudioMetrics(
    currentSpot,
    solveResult,
    statusMessage,
    selectedSample,
    copy,
    locale
  );
  const draftIssueTone = issueSeverity(draftBuild.issues);

  const handleSelectSample = (sampleId: string) => {
    const nextSample = sampleSpots.find((sample) => sample.id === sampleId);
    if (!nextSample) {
      return;
    }

    setSelectedSample(nextSample);
    setSelectedSampleId(nextSample.id);
    setBuilderDraft(createSpotBuilderDraftFromPreset(nextSample));
    setSolveResult(null);
    setStatusMessage(studio.loadedSample(nextSample.title));
  };

  const handleReset = () => {
    if (!selectedSample) {
      return;
    }

    setBuilderDraft(createSpotBuilderDraftFromPreset(selectedSample));
    setSolveResult(null);
    setStatusMessage(studio.resetTo(selectedSample.title));
  };

  const handleRunSolve = async (draftOverride?: SpotBuilderDraft) => {
    const nextDraft = draftOverride ?? builderDraft;
    if (draftOverride) {
      setBuilderDraft(draftOverride);
    }

    const nextStudioDraft = createStudioDraftFromForm(nextDraft, selectedSample, locale);
    const nextBuild = buildSolverStudioRequest(nextStudioDraft, createDefaultStudioSpot());
    if (nextBuild.issues.some((issue) => issue.severity === "error")) {
      setSolveResult(null);
      setStatusMessage(studio.completeFields);
      return;
    }

    setIsSolving(true);
    setStatusMessage(studio.solving(nextBuild.spot.treePresetId));

    try {
      const result = await runSolverStudioSolve(
        mapSolveRequestToRuntimeRequest(nextBuild.request)
      );
      setSolveResult(result);
      setSolveHistory((current) => [
        {
          id: `${nextBuild.spot.id}-${Date.now()}`,
          title: nextBuild.spot.label,
          action: result.response.chosenAction || "pending",
          presetId: result.response.presetId,
          board: [...nextBuild.request.board],
          cacheHit: Boolean(result.response.cacheHit),
          warnings: [...result.response.warnings],
        },
        ...current.filter((entry) => entry.title !== nextBuild.spot.label).slice(0, 7),
      ]);
      setStatusMessage(describeSolverStudioResult(result, locale));
    } catch (error) {
      const reason = error instanceof Error ? error.message : locale === "fr" ? "solve impossible" : "solve failed";
      setSolveResult(null);
      setStatusMessage(studio.solveFailed(reason));
    } finally {
      setIsSolving(false);
    }
  };

  const solvePanelResult = solveResult
    ? {
        chosenAction: solveResult.response.chosenAction,
        actions: solveResult.response.actions.map((action) => ({
          name: action.name,
          label: action.label,
          size: action.size,
          frequency: action.frequency,
          ev: action.ev,
          isRecommended: action.isRecommended,
        })),
        heroEv: solveResult.response.heroEv,
        exploitability: solveResult.response.exploitability,
        cacheHit: solveResult.response.cacheHit,
        elapsedMs: solveResult.response.elapsedMs,
        presetId: solveResult.response.presetId,
        warnings: solveResult.response.warnings,
        confidence: solveResult.response.confidence,
        fallbackReason: solveResult.response.fallbackReason,
        incidents: solveResult.response.incidents,
        gateDecision: solveResult.response.gateDecision,
      }
    : null;
  const statusSignals: Signal[] = [
    {
      label: studio.signals.runtime,
      value: solveResult?.transport.source === "http" ? "HTTP /v2/solve" : common.ready,
      note: studio.signals.localReady,
    },
    {
      label: studio.signals.fallback,
      value: localizeSolveStatus(solveResult?.status, locale),
      note: solveResult?.message ?? studio.signals.fallbackIdle,
    },
    {
      label: studio.signals.spot,
      value: `${currentSpot.numPlayers}p · ${inferStudioStreet(currentSpot.board)}`,
      note:
        currentSpot.board.length > 0
          ? currentSpot.board.join(" ")
          : studio.metricDetails.boardPreflop,
    },
  ];
  const spotNavigatorEntries = sampleSpots.map((sample) => ({
    id: sample.id,
    title: sample.title,
    subtitle: sample.description,
    board: [...sample.request.board],
    tags: [sample.request.treePresetId, `${sample.request.numPlayers}p`],
    statusLabel: sample.id === selectedSampleId ? (locale === "fr" ? "actif" : "active") : undefined,
  }));

  return (
    <div className="surface-page">
      <Box
        className="glass-card"
        sx={{
          borderRadius: 5,
          p: { xs: 2, md: 2.5 },
          display: "grid",
          gap: 1.75,
        }}
      >
        <Stack
          direction={{ xs: "column", xl: "row" }}
          spacing={1.5}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", xl: "center" }}
        >
          <Box>
            <Typography variant="overline" sx={{ color: "#526173", letterSpacing: "0.16em" }}>
              {studio.pageLabel}
            </Typography>
            <Typography variant="h5">{studio.title}</Typography>
            <Typography variant="body2" sx={{ color: "#667085", maxWidth: "64ch", mt: 0.75 }}>
              {studio.subtitle}
            </Typography>
          </Box>

          <Stack
            direction={{ xs: "column", md: "row" }}
            spacing={1.25}
            sx={{ width: { xs: "100%", xl: "auto" } }}
          >
            <TextField
              select
              label={studio.sampleLabel}
              value={selectedSampleId}
              onChange={(event) => handleSelectSample(event.target.value)}
              sx={{ minWidth: { xs: "100%", md: 320 } }}
            >
              {sampleSpots.map((sample) => (
                <MenuItem key={sample.id} value={sample.id}>
                  {sample.title}
                </MenuItem>
              ))}
            </TextField>
            <Button variant="contained" onClick={() => void handleRunSolve()} disabled={isSolving}>
              {isSolving ? (locale === "fr" ? "Calcul en cours..." : "Solving...") : studio.solveButton}
            </Button>
            <Button variant="outlined" color="inherit" onClick={handleReset} disabled={isSolving}>
              {studio.resetButton}
            </Button>
          </Stack>
        </Stack>

        <Alert severity={resultState === "error" ? "error" : "info"} variant="outlined">
          {statusMessage}
        </Alert>

        {draftBuild.issues.length > 0 ? (
          <Alert severity={draftIssueTone} variant="outlined">
            <Stack spacing={0.5}>
              {draftBuild.issues.map((issue) => (
                <span key={`${issue.field}-${issue.message}`}>{issue.message}</span>
              ))}
            </Stack>
          </Alert>
        ) : null}
      </Box>

      <Box
        sx={{
          display: "grid",
          gap: 2.5,
          gridTemplateColumns: {
            xs: "1fr",
            xl: "minmax(0, 1.08fr) minmax(360px, 0.92fr)",
          },
        }}
      >
        <SpotBuilderForm
          value={builderDraft}
          onChange={setBuilderDraft}
          onSubmit={(nextDraft) => {
            void handleRunSolve(nextDraft);
          }}
          onReset={handleReset}
          loading={isSolving}
          presetOptions={presetOptions}
          locale={locale}
          title={studio.spotFormTitle}
          subtitle={studio.spotFormSubtitle}
          submitLabel={studio.solveButton}
          resetLabel={studio.resetButton}
        />
        <SolveResultsPanel
          state={resultState}
          result={solvePanelResult}
          locale={locale}
          onRetry={() => {
            void handleRunSolve();
          }}
          title={studio.resultsTitle}
          subtitle={studio.resultsSubtitle}
        />
      </Box>
    </div>
  );
}

export function BotCockpitPage() {
  const { locale } = useWorkstationI18n();
  const { botCopy } = useWorkstationText(locale);
  const [cockpitPayload, setCockpitPayload] = useState<BotCockpitPayload>(() =>
    createDefaultBotCockpitPayload({
      message: botCopy.loading,
    })
  );
  const [isRefreshing, setIsRefreshing] = useState(true);
  const [isOperatorSyncing, setIsOperatorSyncing] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>(botCopy.connecting);
  const [runtimeHistoryOverride, setRuntimeHistoryOverride] = useState<string[]>([]);
  const [historyViewMode, setHistoryViewMode] = useState<CockpitHistoryViewMode>(() => {
    if (typeof window === "undefined") {
      return "combined";
    }

    const storedValue = window.localStorage.getItem(BOT_COCKPIT_HISTORY_VIEW_STORAGE_KEY);
    return storedValue === "runtime" || storedValue === "persisted" || storedValue === "combined"
      ? storedValue
      : "combined";
  });
  const [displayMode, setDisplayMode] = useState<"page" | "widget">(() => {
    if (typeof window === "undefined") {
      return "page";
    }
    const storedValue = window.localStorage.getItem(BOT_COCKPIT_DISPLAY_MODE_STORAGE_KEY);
    if (storedValue === "page" || storedValue === "widget") {
      return storedValue;
    }
    return window.innerWidth <= 900 ? "widget" : "page";
  });

  useEffect(() => {
    let isActive = true;

    loadBotCockpitPayload()
      .then(async (payload) => {
        if (!isActive) {
          return;
        }
        const runtimeHistory = await loadBotCockpitRuntimeHistory({
          source: deriveBotCockpitHistorySource(payload) ?? undefined,
        }).catch(() => []);
        if (!isActive) {
          return;
        }
        setCockpitPayload(payload);
        setRuntimeHistoryOverride(runtimeHistory);
        setStatusMessage(describeBotCockpitPayload(payload, locale));
      })
      .catch((error) => {
        if (!isActive) {
          return;
        }
        const reason =
          error instanceof Error
            ? error.message
            : locale === "fr"
              ? "bridge Bot Cockpit indisponible"
              : "cockpit bridge unavailable";
        const fallback = createDefaultBotCockpitPayload({
          message: reason,
        });
        setCockpitPayload(fallback);
        setRuntimeHistoryOverride([]);
        setStatusMessage(
          locale === "fr" ? `Bot Cockpit indisponible : ${reason}` : `Bot Cockpit unavailable: ${reason}`
        );
      })
      .finally(() => {
        if (isActive) {
          setIsRefreshing(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [locale]);
  const isBusy = isRefreshing || isOperatorSyncing;

  const handleRefresh = useCallback(async () => {
    if (isBusy) {
      return;
    }
    setIsRefreshing(true);
    setStatusMessage(botCopy.refresh);
    try {
      const refreshed = await refreshBotCockpitPayload();
      const runtimeHistory = await loadBotCockpitRuntimeHistory({
        source: deriveBotCockpitHistorySource(refreshed) ?? undefined,
      }).catch(() => []);
      setCockpitPayload(refreshed);
      setRuntimeHistoryOverride(runtimeHistory);
      setStatusMessage(describeBotCockpitPayload(refreshed, locale));
    } catch (error) {
      const reason = error instanceof Error ? error.message : locale === "fr" ? "rafraîchissement impossible" : "refresh failed";
      setStatusMessage(botCopy.refreshFailed(reason));
    } finally {
      setIsRefreshing(false);
    }
  }, [botCopy, isBusy, locale]);

  const commitOperatorPatch = useCallback(
    async (patch: Parameters<typeof persistBotCockpitOperatorState>[0]) => {
      if (isBusy) {
        return;
      }
      setIsOperatorSyncing(true);
      setStatusMessage(
        locale === "fr"
          ? "Mise à jour des contrôles opérateur..."
          : "Updating operator controls..."
      );
      try {
        const updatedPayload = await persistBotCockpitOperatorState(patch);
        const runtimeHistory = await loadBotCockpitRuntimeHistory({
          source: deriveBotCockpitHistorySource(updatedPayload) ?? undefined,
        }).catch(() => []);
        setCockpitPayload(updatedPayload);
        setRuntimeHistoryOverride(runtimeHistory);
        setStatusMessage(describeBotCockpitPayload(updatedPayload, locale));
      } catch (error) {
        const reason =
          error instanceof Error
            ? error.message
            : locale === "fr"
              ? "mise à jour impossible"
              : "operator update failed";
        setStatusMessage(botCopy.refreshFailed(reason));
      } finally {
        setIsOperatorSyncing(false);
      }
    },
    [botCopy, isBusy, locale]
  );

  const handleCaptureSpot = () => {
    try {
      if (typeof localStorage !== "undefined") {
        localStorage.setItem(
          CAPTURED_COCKPIT_SPOT_STORAGE_KEY,
          JSON.stringify({
            capturedAt: new Date().toISOString(),
            spot: cockpitPayload.spot,
            decision: cockpitPayload.decision,
            ocr: cockpitPayload.ocr,
            notes: cockpitPayload.notes,
          })
        );
        setStatusMessage(botCopy.captureStored);
        return;
      }
    } catch (error) {
      const reason =
        error instanceof Error ? error.message : locale === "fr" ? "stockage local indisponible" : "storage unavailable";
      setStatusMessage(botCopy.captureFailed(reason));
      return;
    }

    setStatusMessage(botCopy.captureMemory);
  };

  const handleToggleShadowMode = useCallback(async () => {
    const nextValue = !cockpitPayload.operator.shadowModeEnabled;
    await commitOperatorPatch({
      shadowModeEnabled: nextValue,
    });
  }, [cockpitPayload.operator.shadowModeEnabled, commitOperatorPatch]);

  const handleToggleAssistedMode = useCallback(async () => {
    const nextValue = !cockpitPayload.operator.assistedModeEnabled;
    await commitOperatorPatch({
      assistedModeEnabled: nextValue,
    });
  }, [cockpitPayload.operator.assistedModeEnabled, commitOperatorPatch]);

  const handleToggleObservationMode = useCallback(async () => {
    const nextValue = !cockpitPayload.operator.observationModeEnabled;
    await commitOperatorPatch({
      observationModeEnabled: nextValue,
    });
  }, [cockpitPayload.operator.observationModeEnabled, commitOperatorPatch]);

  const handleToggleManualOverride = useCallback(async () => {
    const nextValue = !cockpitPayload.operator.manualOverrideEnabled;
    await commitOperatorPatch({
      manualOverrideEnabled: nextValue,
    });
  }, [cockpitPayload.operator.manualOverrideEnabled, commitOperatorPatch]);

  const handleTogglePaused = useCallback(async () => {
    const nextValue = !cockpitPayload.operator.paused;
    await commitOperatorPatch({
      paused: nextValue,
    });
  }, [cockpitPayload.operator.paused, commitOperatorPatch]);

  useEffect(() => {
    if (isBusy || cockpitPayload.operator.paused || !cockpitPayload.operator.autoRefreshEnabled) {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      void handleRefresh();
    }, BOT_COCKPIT_AUTO_REFRESH_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [
    cockpitPayload.operator.autoRefreshEnabled,
    cockpitPayload.operator.paused,
    handleRefresh,
    isBusy,
  ]);

  const cockpitSpot = mapBotCockpitSpotToSnapshot(cockpitPayload.spot, cockpitPayload.ocr);
  const cockpitHistoryState = buildCockpitHistoryState(cockpitPayload.spot, runtimeHistoryOverride);
  const activeHistoryMode = cockpitHistoryState.availableModes.includes(historyViewMode)
    ? historyViewMode
    : cockpitHistoryState.availableModes[0] ?? "combined";
  const cockpitHistory = cockpitHistoryState[activeHistoryMode];
  const cockpitDecision = mapBotCockpitDecisionToSnapshot(cockpitPayload.decision);
  const decisionState = mapBotCockpitDecisionState(cockpitPayload, isBusy);
  const operatorMode = mapBotCockpitOperatorMode(
    cockpitPayload.operator,
    cockpitPayload
  );
  const operatorAlerts = buildBotCockpitAlerts(cockpitPayload, locale);
  const operatorMetrics = buildBotCockpitOperatorMetrics(cockpitPayload, locale);
  const cockpitDecisionMetadata = asRawRecord(cockpitPayload.decision.metadata);
  const warningHistory = Array.from(
    new Set([
      ...cockpitPayload.warnings,
      ...cockpitPayload.decision.warnings,
      ...readRawStringArray(cockpitDecisionMetadata.warning_history),
    ])
  );
  const fallbackHistory = Array.from(
    new Set([
      ...readRawStringArray(cockpitDecisionMetadata.fallback_history),
      ...(cockpitDecision.fallbackHistory ?? []),
      ...(cockpitPayload.decision.source === "fallback" ? ["fallback_used"] : []),
    ])
  );
  const runtimeEventHistory = asRawArray(cockpitDecisionMetadata.runtime_event_history)
    .map((entry) => asRawRecord(entry))
    .map((entry) => {
      const kind = readRawString(entry.kind, "event");
      const message = readRawString(entry.message, "runtime_update");
      return `${kind}: ${message}`;
    })
    .filter((entry) => entry.length > 0);
  const incidentHistory = Array.from(
    new Set([
      ...readRawStringArray(cockpitDecisionMetadata.incidents),
      ...runtimeEventHistory,
      ...(cockpitDecision.incidents ?? []).map((incident) => incident.id),
    ])
  );
  const decisionExplanation =
    readRawString(cockpitDecisionMetadata.explanation, "") ||
    (locale === "fr"
      ? "La decision suit la meilleure branche visible du traceur, avec blocage automatique si le gate de confiance devient douteux."
      : "The decision follows the best visible branch in the trace, with automatic blocking if the confidence gate becomes doubtful.");
  const cockpitHistorySource = deriveBotCockpitHistorySource(cockpitPayload);
  const cockpitSpotMetadata = asRawRecord(cockpitPayload.spot.metadata);
  const cockpitTableName =
    readRawString(cockpitSpotMetadata.table_name, "") ||
    readRawString(cockpitSpotMetadata.table, "") ||
    readRawString(cockpitSpotMetadata.tableName, "");
  const cockpitHandId =
    readRawString(cockpitSpotMetadata.hand_id, "") ||
    readRawString(cockpitSpotMetadata.handId, "") ||
    readRawString(cockpitSpotMetadata.session_id, "");
  const [persistedHistoryBundleAt, setPersistedHistoryBundleAt] = useState<string | null>(() => {
    if (typeof window === "undefined") {
      return null;
    }

    return parseBotCockpitHistoryBundle(
      window.localStorage.getItem(BOT_COCKPIT_HISTORY_BUNDLE_STORAGE_KEY)
    )?.exportedAt ?? null;
  });

  const historyBundle: BotCockpitHistoryBundle = {
    version: 1,
    exportedAt: new Date().toISOString(),
    historyView: activeHistoryMode,
    availableHistoryViews: cockpitHistoryState.availableModes,
    source: cockpitHistorySource,
    refreshedAt: cockpitPayload.refreshedAt,
    tableName: cockpitTableName,
    handId: cockpitHandId,
    currentAction: cockpitPayload.decision.chosenAction,
    decisionSource: cockpitPayload.decision.source,
    persistedHistory: cockpitHistoryState.persisted,
    runtimeHistory: cockpitHistoryState.runtime,
    combinedHistory: cockpitHistoryState.combined,
    warningHistory,
    fallbackHistory,
    incidentHistory,
  };

  const handleExportHistoryBundle = () => {
    if (typeof window === "undefined") {
      return;
    }

    try {
      const filename = [
        "bot-cockpit-history",
        cockpitHandId || "session",
        activeHistoryMode,
      ]
        .filter((entry) => entry.length > 0)
        .join("-")
        .replace(/[^a-zA-Z0-9-_]+/g, "_");
      const blob = new Blob([JSON.stringify(historyBundle, null, 2)], {
        type: "application/json;charset=utf-8",
      });
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${filename}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
      setStatusMessage(
        locale === "fr"
          ? "Le bundle d'historique a ete exporte en JSON."
          : "The history bundle was exported as JSON."
      );
    } catch (error) {
      const reason = error instanceof Error ? error.message : locale === "fr" ? "export impossible" : "export failed";
      setStatusMessage(
        locale === "fr"
          ? `L'export de l'historique a echoue : ${reason}`
          : `History export failed: ${reason}`
      );
    }
  };

  useEffect(() => {
    if (!cockpitHistoryState.availableModes.includes(historyViewMode)) {
      setHistoryViewMode(cockpitHistoryState.availableModes[0] ?? "combined");
      return;
    }

    if (typeof window !== "undefined") {
      window.localStorage.setItem(BOT_COCKPIT_HISTORY_VIEW_STORAGE_KEY, historyViewMode);
    }
  }, [cockpitHistoryState.availableModes, historyViewMode]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(BOT_COCKPIT_DISPLAY_MODE_STORAGE_KEY, displayMode);
    }
  }, [displayMode]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    try {
      window.localStorage.setItem(
        BOT_COCKPIT_HISTORY_BUNDLE_STORAGE_KEY,
        JSON.stringify(historyBundle)
      );
      setPersistedHistoryBundleAt(historyBundle.exportedAt);
    } catch {
      // Keep the panel usable even when browser storage is unavailable.
    }
  }, [historyBundle]);

  const handleSetAutomation = useCallback(async (enabled: boolean) => {
    if (enabled) {
      await commitOperatorPatch({
        paused: false,
        assistedModeEnabled: false,
        observationModeEnabled: false,
        shadowModeEnabled: false,
        manualOverrideEnabled: false,
      });
      return;
    }

    await commitOperatorPatch({
      paused: true,
    });
  }, [commitOperatorPatch]);

  return (
    <div className="surface-page">
      <Box
        className="glass-card"
        sx={{
          borderRadius: 5,
          p: { xs: 2, md: 2.5 },
          display: "grid",
          gap: 1.25,
        }}
      >
        <Typography variant="overline" sx={{ color: "#526173", letterSpacing: "0.16em" }}>
          {locale === "fr" ? "Affichage" : "Display"}
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} useFlexGap flexWrap="wrap">
          <Button
            variant={displayMode === "widget" ? "contained" : "outlined"}
            onClick={() => setDisplayMode("widget")}
          >
            {locale === "fr" ? "Widget latéral" : "Side widget"}
          </Button>
          <Button
            variant={displayMode === "page" ? "contained" : "outlined"}
            onClick={() => setDisplayMode("page")}
          >
            {locale === "fr" ? "Vue complète" : "Full view"}
          </Button>
        </Stack>
      </Box>

      {displayMode === "widget" ? (
        <BotLiveWidget
          locale={locale}
          spot={{ ...cockpitSpot, actionHistory: cockpitHistory }}
          decision={cockpitDecision}
          statusMessage={statusMessage}
          loading={isBusy}
          paused={cockpitPayload.operator.paused}
          refreshLabel={botCopy.refreshButton}
          refreshingLabel={botCopy.refreshingButton}
          pauseLabel={botCopy.pauseLabel}
          resumeLabel={botCopy.resumeLabel}
          onRefresh={() => {
            void handleRefresh();
          }}
          onTogglePaused={handleTogglePaused}
        />
      ) : (
        <>
      <BotCockpitControlDesk
        locale={locale}
        payload={cockpitPayload}
        statusMessage={statusMessage}
        mode={operatorMode}
        alerts={operatorAlerts}
        metrics={operatorMetrics}
        loading={isBusy}
        refreshLabel={botCopy.refreshButton}
        refreshingLabel={botCopy.refreshingButton}
        captureLabel={botCopy.captureButton}
        assistedLabel={botCopy.assistedLabel}
        observationLabel={botCopy.observationLabel}
        shadowLabel={botCopy.shadowLabel}
        manualOverrideLabel={botCopy.manualLabel}
        pauseLabel={botCopy.pauseLabel}
        resumeLabel={botCopy.resumeLabel}
        onRefresh={() => {
          void handleRefresh();
        }}
        onCaptureSpot={handleCaptureSpot}
        onToggleAssistedMode={handleToggleAssistedMode}
        onToggleObservationMode={handleToggleObservationMode}
        onToggleShadowMode={handleToggleShadowMode}
        onToggleManualOverride={handleToggleManualOverride}
        onTogglePaused={handleTogglePaused}
        onSetAutomation={handleSetAutomation}
      />
      <Box
        sx={{
          display: "grid",
          gap: 2.5,
          gridTemplateColumns: {
            xs: "1fr",
            xl: "minmax(0, 1fr) minmax(0, 1fr)",
          },
        }}
      >
        <LiveTableSnapshotCard
          locale={locale}
          spot={{ ...cockpitSpot, actionHistory: cockpitHistory }}
          decision={cockpitDecision}
          loading={isBusy}
          title={botCopy.liveViewTitle}
          subtitle={botCopy.liveViewSubtitle}
          historyView={activeHistoryMode}
          availableHistoryViews={cockpitHistoryState.availableModes}
          onHistoryViewChange={setHistoryViewMode}
        />
        <DecisionTracePanel
          state={decisionState}
          decision={cockpitDecision}
          spot={{ ...cockpitSpot, actionHistory: cockpitHistory }}
          locale={locale}
          title={botCopy.traceTitle}
          subtitle={botCopy.traceSubtitle}
          emptyMessage={botCopy.traceEmpty}
          fallbackMessage={botCopy.traceFallback}
          errorMessage={botCopy.traceError}
          loadingMessage={botCopy.traceLoading}
          historyView={activeHistoryMode}
          availableHistoryViews={cockpitHistoryState.availableModes}
          onHistoryViewChange={setHistoryViewMode}
          onRetry={() => {
            void handleRefresh();
          }}
        />
      </Box>
        </>
      )}
    </div>
  );
}

export function ReplayAnalyticsPage() {
  const { locale } = useWorkstationI18n();
  const text = useWorkstationText(locale);
  const common = text.t((c) => c.common);
  const { replayCopy } = text;
  const [replayPayload, setReplayPayload] = useState<ReplayBridgePayload | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(true);
  const [statusMessage, setStatusMessage] = useState<string>(replayCopy.loading);
  const [selectedSpotId, setSelectedSpotId] = useState("");
  const [importedBundleName, setImportedBundleName] = useState("");
  const [importedBundleAt, setImportedBundleAt] = useState("");
  const [importedCompareState, setImportedCompareState] = useState<PolicyCompareImportState | null>(null);
  const [runtimeReplayPayload, setRuntimeReplayPayload] = useState<ReplayBridgePayload | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const compareFileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let isActive = true;

    loadReplayAnalyticsPayload()
      .then((payload) => {
        if (!isActive) {
          return;
        }
        setReplayPayload(payload);
        setRuntimeReplayPayload(payload);
        setStatusMessage(payload.recommendations[0] ?? payload.notes[0] ?? replayCopy.loaded);
        const nextItems = buildReplayTimelineItems(payload);
        if (nextItems.length > 0) {
          setSelectedSpotId(nextItems[0].id);
        }
      })
      .catch((error) => {
        if (!isActive) {
          return;
        }
        const reason =
          error instanceof Error
            ? error.message
            : locale === "fr"
              ? "payload replay indisponible"
              : "replay payload unavailable";
        setStatusMessage(replayCopy.offline(reason));
      })
      .finally(() => {
        if (isActive) {
          setIsRefreshing(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [locale, replayCopy.offline]);

  const isImportedBundle = importedBundleName.length > 0;
  const replayState = mapReplayPageState(replayPayload, isRefreshing);
  const replayReviewQueue = replayPayload
    ? buildReplayReviewQueue(replayPayload, locale)
    : { items: [], sortedByImpact: false, impactSummary: replayCopy.waitingRecommendationsNote };
  const replayTimelineItems = replayReviewQueue.items;
  const replaySelectedSpot =
    replayTimelineItems.find((item) => item.id === selectedSpotId) ?? replayTimelineItems[0];
  const replaySessionName = replayPayload
    ? readRawString(
        getReplaySourceRecord(replayPayload).selected_session_id ?? getReplaySourceRecord(replayPayload).session_id,
        locale === "fr" ? "Session locale de relecture" : "Local replay review"
      )
    : locale === "fr"
      ? "Session locale de relecture"
      : "Local replay review";
  const replayPolicyCompareAggregate =
    readReplayPolicyCompareAggregate(replayPayload?.raw, replaySessionName) ??
    buildReplayPolicyCompareAggregate(replayTimelineItems, replaySessionName, locale);
  const replayMetricsLive = replayPayload ? buildReplayPageMetrics(replayPayload, locale) : getReplayFallbackMetrics(locale);
  const replayBundleSections = replayPayload ? buildReplayBundleSections(replayPayload, locale) : [];
  const replaySignals = replayPayload
    ? buildReplaySignals(replayPayload, replaySelectedSpot, locale)
    : [
        { label: replayCopy.source, value: replayCopy.waitingSource, note: replayCopy.loading },
        {
          label: locale === "fr" ? "Sélection" : "Selection",
          value: replayCopy.waitingSelection,
          note: replayCopy.waitingSelectionNote,
        },
        {
          label: locale === "fr" ? "Recommandations" : "Recommendations",
          value: replayCopy.waitingRecommendations,
          note: replayCopy.waitingRecommendationsNote,
        },
      ];
  const isImportedCompare = importedCompareState !== null;

  useEffect(() => {
    if (replayTimelineItems.length === 0) {
      return;
    }
    if (!replayTimelineItems.some((item) => item.id === selectedSpotId)) {
      setSelectedSpotId(replayTimelineItems[0].id);
    }
  }, [replayTimelineItems, selectedSpotId]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setStatusMessage(replayCopy.refresh);
    try {
      const payload = await refreshReplayAnalyticsPayload();
      setRuntimeReplayPayload(payload);
      setReplayPayload(payload);
      setImportedBundleName("");
      setImportedBundleAt("");
      setImportedCompareState(null);
      const nextItems = buildReplayTimelineItems(payload, locale);
      if (nextItems.length > 0) {
        setSelectedSpotId((currentSelection) =>
          nextItems.some((item) => item.id === currentSelection)
            ? currentSelection
            : nextItems[0].id
        );
      }
      setStatusMessage(describeReplayPayload(payload, locale));
    } catch (error) {
      const reason = error instanceof Error ? error.message : locale === "fr" ? "rafraîchissement impossible" : "refresh failed";
      setStatusMessage(replayCopy.refreshFailed(reason));
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleImportBundle = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      const content = await file.text();
      const parsed = JSON.parse(content) as unknown;
      const imported = resolveReplayBundleImport(parsed, locale, replaySessionName);
      setReplayPayload(imported.payload);
      setImportedBundleName(file.name);
      setImportedBundleAt(imported.importedAt);
      setImportedCompareState(null);
      const nextItems = buildReplayTimelineItems(imported.payload, locale);
      const matchedSpot = imported.selectedSpotId
        ? nextItems.find((item) => item.id === imported.selectedSpotId)
        : undefined;
      setSelectedSpotId(matchedSpot?.id ?? nextItems[0]?.id ?? imported.selectedSpotId ?? "");
      setStatusMessage(imported.statusMessage ?? imported.payload.recommendations[0] ?? replayCopy.importLoaded(file.name));
    } catch (error) {
      const reason = error instanceof Error ? error.message : locale === "fr" ? "JSON invalide" : "invalid JSON";
      setStatusMessage(replayCopy.importFailed(reason));
    } finally {
      event.target.value = "";
    }
  };

  const handleResetImportedBundle = () => {
    const nextPayload = runtimeReplayPayload ?? createDefaultReplayAnalyticsPayload();
    setReplayPayload(nextPayload);
    setImportedBundleName("");
    setImportedBundleAt("");
    setImportedCompareState(null);
    const nextItems = buildReplayTimelineItems(nextPayload, locale);
    setSelectedSpotId(nextItems[0]?.id ?? "");
    setStatusMessage(describeReplayPayload(nextPayload, locale) || replayCopy.importReset);
  };

  const handleResetImportedCompare = () => {
    const nextPayload = runtimeReplayPayload ?? createDefaultReplayAnalyticsPayload();
    setReplayPayload(nextPayload);
    setImportedCompareState(null);
    const nextItems = buildReplayTimelineItems(nextPayload, locale);
    setSelectedSpotId(nextItems[0]?.id ?? "");
    setStatusMessage(describeReplayPayload(nextPayload, locale) || replayCopy.compareImportReset);
  };

  const handleExportReviewPack = () => {
    if (!replayPayload) {
      setStatusMessage(replayCopy.exportFailed);
      return;
    }

    const exportedAt = new Date().toISOString();
    const analytics = mapRuntimeSnapshotToReplayAnalyticsPayload(asRawRecord(replayPayload.raw));
    const reviewPack = createReplayReviewPack({
      exportedAt,
      locale,
      sessionLabel: replaySessionName,
      source: replayPayload.source,
      status: replayPayload.status,
      runtime: replayPayload.runtime,
      analytics,
      currentReplay: {
        selectedSpotId: replaySelectedSpot?.id,
        selectedSpot: buildReplayReviewPackSpot(replaySelectedSpot, true),
        timelineCount: replayTimelineItems.length,
        sortedByImpact: replayReviewQueue.sortedByImpact,
        impactSummary: replayReviewQueue.impactSummary,
        policyCompare: replayPolicyCompareAggregate,
        signals: replaySignals.map((signal) => ({
          label: signal.label,
          value: signal.value,
          note: signal.note,
        })),
        timeline: replayTimelineItems.map((item) => buildReplayReviewPackSpot(item, item.id === replaySelectedSpot?.id)).filter(Boolean),
      },
      warnings: replayPayload.warnings,
      recommendations: replayPayload.recommendations,
      notes: replayPayload.notes,
      raw: replayPayload.raw,
    });
    const stamp = exportedAt.slice(0, 10);
    downloadJsonFile(`review-pack-${sanitizeFileNameSegment(replaySessionName)}-${stamp}.json`, reviewPack);
    setStatusMessage(replayCopy.exportReady);
  };

  const handleImportPolicyCompare = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      const content = await file.text();
      const parsed = JSON.parse(content) as unknown;
      const imported = readReplayPolicyCompareExchange(parsed);
      if (!imported || (!imported.aggregate && !imported.selectedSpot && !imported.raw)) {
        throw new Error(locale === "fr" ? "format policy compare incompatible" : "incompatible policy compare format");
      }

      const payload = hydrateReplayAnalyticsPayloadFromBundle(imported.raw ?? parsed);
      setReplayPayload(payload);
      setImportedBundleName("");
      setImportedBundleAt("");
      setImportedCompareState({
        fileName: file.name,
        importedAt: imported.exportedAt,
        sessionLabel: imported.sessionLabel ?? replaySessionName,
        source: imported.source ?? "local-json",
      });

      const nextItems = buildReplayTimelineItems(payload, locale);
      const importedSpotId = imported.selectedSpot?.id;
      const matchedSpot = importedSpotId ? nextItems.find((item) => item.id === importedSpotId) : undefined;
      setSelectedSpotId(matchedSpot?.id ?? nextItems[0]?.id ?? importedSpotId ?? "");
      setStatusMessage(imported.selectedSpot?.note ?? replayCopy.compareImportLoaded(file.name));
    } catch (error) {
      const reason = error instanceof Error ? error.message : locale === "fr" ? "JSON invalide" : "invalid JSON";
      setStatusMessage(replayCopy.compareImportFailed(reason));
    } finally {
      event.target.value = "";
    }
  };

  const replayAlertSeverity =
    replayState === "error"
      ? "error"
      : replayState === "degraded" || replayState === "offline"
        ? "warning"
        : "info";

  return (
    <div className="surface-page">
      <Box
        className="glass-card"
        sx={{
          borderRadius: 5,
          p: { xs: 2, md: 2.5 },
          display: "grid",
          gap: 1.75,
        }}
      >
        <Stack
          direction={{ xs: "column", xl: "row" }}
          spacing={2}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", xl: "center" }}
        >
          <Box>
            <Typography variant="overline" sx={{ color: "#526173", letterSpacing: "0.16em" }}>
              {replayCopy.reviewLabel}
            </Typography>
            <Typography variant="h5">{replayCopy.title}</Typography>
            <Typography variant="body2" sx={{ color: "#667085", maxWidth: "64ch", mt: 0.75 }}>
              {replayCopy.subtitle}
            </Typography>
          </Box>

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.25}>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={(event) => {
                void handleImportBundle(event);
              }}
            />
            <Button
              variant="outlined"
              startIcon={<UploadFileRoundedIcon />}
              onClick={() => fileInputRef.current?.click()}
            >
              {replayCopy.importButton}
            </Button>
            {isImportedBundle ? (
              <Button variant="text" onClick={handleResetImportedBundle} disabled={isRefreshing}>
                {replayCopy.importResetButton}
              </Button>
            ) : null}
            <Button variant="contained" onClick={() => void handleRefresh()} disabled={isRefreshing}>
              {isRefreshing ? replayCopy.refreshingButton : replayCopy.refreshButton}
            </Button>
          </Stack>
        </Stack>

        <Typography variant="body2" sx={{ color: "#667085" }}>
          {replayCopy.importHint}
        </Typography>

        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          <Chip
            label={`${replayCopy.source} · ${replayPayload?.source ?? replayCopy.waitingSource}`}
            color={replayPayload?.source === "tauri" ? "primary" : "default"}
            variant="outlined"
          />
          <Chip
            label={`${replayCopy.status} · ${replayPayload?.status ?? common.loading.toLowerCase()}`}
            variant="outlined"
          />
          {replayPayload
            ? buildReplayHeadlineTags(replayPayload).map((tag) => (
                <Chip key={tag} label={tag} variant="outlined" />
              ))
            : null}
        </Stack>

        <Alert severity={replayAlertSeverity} variant="outlined">
          {statusMessage}
        </Alert>

        {isImportedBundle ? (
          <Box
            sx={{
              borderRadius: 4,
              border: "1px solid rgba(103, 80, 164, 0.18)",
              bgcolor: "rgba(103, 80, 164, 0.05)",
              p: 2,
            }}
          >
            <Stack spacing={1.5}>
              <Box>
                <Typography variant="subtitle1">{replayCopy.importPanelTitle}</Typography>
                <Typography variant="body2" sx={{ color: "#667085", mt: 0.5 }}>
                  {replayCopy.importPanelSubtitle}
                </Typography>
              </Box>
              <Stack direction={{ xs: "column", md: "row" }} spacing={1} useFlexGap flexWrap="wrap">
                <Chip
                  label={`${replayCopy.importFile} · ${importedBundleName}`}
                  variant="outlined"
                />
                <Chip
                  label={`${replayCopy.importedAt} · ${formatReplayImportedAt(importedBundleAt, locale)}`}
                  variant="outlined"
                />
                <Chip
                  label={`${replayCopy.importedSource} · local-json`}
                  variant="outlined"
                  color="secondary"
                />
              </Stack>
              <Divider flexItem />
              <SessionOverviewPanel
                locale={locale}
                state={replayState}
                title={replayCopy.bundleSectionsTitle}
                subtitle={replayCopy.importPanelSubtitle}
                sessionName={importedBundleName}
                sessionMeta={`${replayPayload?.status ?? "ready"} · ${replayPayload?.source ?? "offline"}`}
                summary={replayPayload?.notes[0] ?? replayCopy.importHint}
                sessionStats={[]}
                trendKpis={[]}
                leakGroups={replayBundleSections}
                headlineTags={replayPayload ? buildReplayHeadlineTags(replayPayload) : []}
              />
            </Stack>
          </Box>
        ) : null}
      </Box>

      <Box>
        <SessionOverviewPanel
          locale={locale}
          state={replayState}
          title={replayCopy.sessionTitle}
          subtitle={replayCopy.sessionSubtitle}
          sessionName={
            replaySessionName
          }
          sessionMeta={
            replayPayload
              ? `${replayPayload.source} · refreshed ${replayPayload.refreshedAt}`
              : replayCopy.loading
          }
          summary={
            replayPayload?.recommendations[0] ??
            replayCopy.waitingRecommendationsNote
          }
          emptyMessage={replayCopy.sessionEmpty}
          sessionStats={replayPayload ? buildReplaySessionStats(replayPayload, locale) : []}
          trendKpis={replayPayload ? buildReplayTrendStats(replayPayload, locale) : []}
          leakGroups={replayPayload ? buildReplayLeakGroups(replayPayload, locale) : []}
          headlineTags={replayPayload ? buildReplayHeadlineTags(replayPayload) : []}
          onReviewLatest={() => {
            if (replayTimelineItems.length > 0) {
              setSelectedSpotId(replayTimelineItems[0].id);
              setStatusMessage(replayCopy.latestFocused(replayTimelineItems[0].title));
            }
          }}
          onOpenTimeline={() => {
            setStatusMessage(replayCopy.timelineReady);
          }}
          onExport={handleExportReviewPack}
        />
      </Box>

      <Box>
        <ReplayTimelinePanel
          locale={locale}
          state={replayState}
          title={replayCopy.timelineTitle}
          subtitle={replayCopy.timelineSubtitle}
          sortedByImpact={replayReviewQueue.sortedByImpact}
          impactSummary={replayReviewQueue.impactSummary}
          emptyMessage={replayCopy.timelineEmpty}
          loadingMessage={replayCopy.timelineLoading}
          items={replayTimelineItems}
          selectedSpotId={replaySelectedSpot?.id}
          onSelectSpot={(spotId) => {
            const selectedSpot = replayTimelineItems.find((item) => item.id === spotId);
            setSelectedSpotId(spotId);
            if (selectedSpot) {
              setStatusMessage(replayCopy.selectedNode(selectedSpot.title));
            }
          }}
          onJumpToLatest={() => {
            if (replayTimelineItems.length > 0) {
              setSelectedSpotId(replayTimelineItems[0].id);
              setStatusMessage(replayCopy.jumpedNode(replayTimelineItems[0].title));
            }
          }}
          onRefresh={() => {
            void handleRefresh();
          }}
        />
      </Box>
    </div>
  );
}

export function ConfigLabPage() {
  const { locale, setLocale } = useWorkstationI18n();
  const text = useWorkstationText(locale);
  const common = text.t((c) => c.common);
  const { mode: themeMode, setMode: setThemeMode } = useWorkstationThemeMode();
  const { configCopy } = text;
  const [configPayload, setConfigPayload] = useState<ConfigBridgePayload | null>(null);
  const [ocrStatus, setOcrStatus] = useState<ConfigLabOcrStatus | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(true);
  const [statusMessage, setStatusMessage] = useState<string>(configCopy.loading);
  const [activePresetId, setActivePresetId] = useState("");
  const [benchmarkProfile, setBenchmarkProfile] = useState("balanced");
  const llmPersistRequestIdRef = useRef(0);

  useEffect(() => {
    let isActive = true;

    loadConfigLabPayload()
      .then(async (payload) => {
        const [persistedOcr, status] = await Promise.all([
          loadPersistedOcrConfig().catch(() => payload.ocr),
          getConfigLabOcrStatus().catch(() => null),
        ]);
        if (!isActive) {
          return;
        }
        const nextPayload = {
          ...payload,
          ocr: persistedOcr,
        };
        const presetItems = buildConfigPresetItems(nextPayload, locale);
        setConfigPayload(nextPayload);
        setActivePresetId(
          presetItems.some((preset) => preset.id === nextPayload.solver.selectedPresetId)
            ? nextPayload.solver.selectedPresetId
            : presetItems[0]?.id ?? nextPayload.solver.selectedPresetId
        );
        setStatusMessage(
          nextPayload.recommendations[0] ??
            nextPayload.warnings[0] ??
            configCopy.loaded
        );
        setOcrStatus(status);
      })
      .catch((error) => {
        if (!isActive) {
          return;
        }
        const reason =
          error instanceof Error
            ? error.message
            : locale === "fr"
              ? "payload config indisponible"
              : "config payload unavailable";
        setStatusMessage(configCopy.offline(reason));
      })
      .finally(() => {
        if (isActive) {
          setIsRefreshing(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [configCopy.offline, locale]);

  const configState = mapConfigRuntimeState(configPayload, isRefreshing);
  const configPresetItems = configPayload ? buildConfigPresetItems(configPayload, locale) : [];
  const activePreset = configPresetItems.find((preset) => preset.id === activePresetId) ?? configPresetItems[0];
  const configMetricsLive = configPayload
    ? buildConfigPageMetrics(configPayload, activePreset?.id ?? activePresetId, locale)
    : getConfigFallbackMetrics(locale);
  const configSignals = configPayload
    ? buildConfigSignals(configPayload, activePreset?.id ?? activePresetId, locale)
    : [
        {
          label: locale === "fr" ? "Fournisseur" : "Provider",
          value: locale === "fr" ? "désactivé" : "disabled",
          note: locale === "fr" ? "L’assistant optionnel est désactivé." : "The optional copilot is disabled.",
        },
        {
          label: configCopy.privacy,
          value: locale === "fr" ? "local strict" : "strict_local",
          note: locale === "fr" ? "Le mode strict local reste la valeur par défaut." : "Strict local remains the default.",
        },
        {
          label: locale === "fr" ? "Préréglage actif" : "Active preset",
          value: locale === "fr" ? "en attente" : "pending",
          note: locale === "fr" ? "En attente d’un payload de configuration." : "Awaiting a config payload.",
        },
      ];
  const configRaw = configPayload ? asRawRecord(configPayload.raw) : {};
  const solverInspection = asRawRecord(configRaw.solver_inspection);
  const researchPayload = asRawRecord(configRaw.research);
  const inspectionItems = [
    ...asRawArray(solverInspection.preset_catalog)
      .slice(0, 4)
      .map((entry) => {
        const record = asRawRecord(entry);
        const tags = readRawStringArray(record.tags);
        const compression = readRawString(record.compression, "balanced");
          return `${readRawString(record.title, readRawString(record.preset_id, locale === "fr" ? "préréglage" : "preset"))} · ${
            locale === "fr" ? localizeSourceLabel(compression, locale) : compression
          } · ${tags.slice(0, 2).join(", ") || (locale === "fr" ? "canonique" : "canonical")}`;
      }),
    ...asRawArray(solverInspection.cache_entries)
      .slice(0, 3)
      .map((entry) => {
        const record = asRawRecord(entry);
        const confidence = readRawNumber(record.decision_confidence, 0);
        return `${readRawString(record.preset_id, "cache")} · ${localizeSourceLabel(readRawString(record.chosen_action, "pending"), locale)} · ${Math.round(confidence * 100)}%`;
      }),
  ];
  const researchItems = [
    ...asRawArray(researchPayload.challengers)
      .slice(0, 4)
      .map((entry) => {
        const record = asRawRecord(entry);
        return `${readRawString(record.id, locale === "fr" ? "challenger" : "challenger")} · ${
          Boolean(record.available) ? (locale === "fr" ? "prêt" : "ready") : locale === "fr" ? "bloqué" : "blocked"
        } · ${locale === "fr" ? localizeSourceLabel(readRawString(record.kind, "lab"), locale) : readRawString(record.kind, "lab")}`;
      }),
    ...asRawArray(researchPayload.range_model_benchmarks)
      .slice(0, 3)
      .map((entry) => {
        const record = asRawRecord(entry);
        return `${readRawString(record.model_version, "range_model")} · score ${readRawNumber(record.score, 0).toFixed(3)}`;
      }),
  ];

  useEffect(() => {
    if (configPresetItems.length === 0) {
      return;
    }
    if (!configPresetItems.some((preset) => preset.id === activePresetId)) {
      setActivePresetId(
        configPresetItems.find((preset) => preset.id === configPayload?.solver.selectedPresetId)?.id ??
          configPresetItems[0].id
      );
    }
  }, [activePresetId, configPayload?.solver.selectedPresetId, configPresetItems]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setStatusMessage(configCopy.refresh);
    try {
      const payload = await refreshConfigLabPayload();
      const [persistedOcr, status] = await Promise.all([
        loadPersistedOcrConfig().catch(() => payload.ocr),
        getConfigLabOcrStatus().catch(() => null),
      ]);
      const nextPayload = {
        ...payload,
        ocr: persistedOcr,
      };
      const presetItems = buildConfigPresetItems(nextPayload, locale);
      setConfigPayload(nextPayload);
      setOcrStatus(status);
      setActivePresetId((currentPresetId) =>
        presetItems.some((preset) => preset.id === currentPresetId)
          ? currentPresetId
          : presetItems.find((preset) => preset.id === nextPayload.solver.selectedPresetId)?.id ??
            presetItems[0]?.id ??
            nextPayload.solver.selectedPresetId
      );
      setStatusMessage(
        describeConfigPayload(nextPayload, locale)
      );
    } catch (error) {
      const reason = error instanceof Error ? error.message : locale === "fr" ? "rafraîchissement impossible" : "refresh failed";
      setStatusMessage(configCopy.refreshFailed(reason));
    } finally {
      setIsRefreshing(false);
    }
  };

  const updateConfigLlm = async (overrides: Partial<UiLlmConfig>, successMessage: string) => {
    if (!configPayload) {
      return;
    }

    const nextProviderMode =
      overrides.enabled === false
        ? "disabled"
        : overrides.enabled === true && configPayload.llm.providerMode === "disabled"
          ? "openai_compatible_local"
          : overrides.providerMode ?? configPayload.llm.providerMode;
    const desiredConfig = toPersistableConfigLabLlm(configPayload, {
      ...overrides,
      providerMode: nextProviderMode,
    });
    const requestId = llmPersistRequestIdRef.current + 1;
    llmPersistRequestIdRef.current = requestId;

    setConfigPayload((currentPayload) =>
      currentPayload ? applyPersistedConfigLabLlm(currentPayload, desiredConfig) : currentPayload
    );
    setStatusMessage(successMessage);

    const persisted = await persistLlmConfig(desiredConfig).catch(() => desiredConfig);
    if (requestId !== llmPersistRequestIdRef.current) {
      return;
    }

    setConfigPayload((currentPayload) =>
      currentPayload ? applyPersistedConfigLabLlm(currentPayload, persisted) : currentPayload
    );
  };

  const updateConfigOcr = async (
    overrides: Partial<ConfigBridgePayload["ocr"]>,
    successMessage: string
  ) => {
    if (!configPayload) {
      return;
    }

    const desiredConfig: ConfigBridgePayload["ocr"] = {
      ...configPayload.ocr,
      ...overrides,
    };

    if (desiredConfig.enabledEngines.length === 0) {
      desiredConfig.enabledEngines = [...DEFAULT_OCR_ENGINES];
    }

    setConfigPayload((currentPayload) =>
      currentPayload
        ? {
            ...currentPayload,
            ocr: desiredConfig,
          }
        : currentPayload
    );
    setStatusMessage(successMessage);

    const persisted = await persistConfigLabOcr(desiredConfig).catch(() => desiredConfig);
    const status = await getConfigLabOcrStatus().catch(() => null);
    setConfigPayload((currentPayload) =>
      currentPayload
        ? {
            ...currentPayload,
            ocr: persisted,
          }
        : currentPayload
    );
    setOcrStatus((currentStatus) => status ?? currentStatus);
  };

  const configAlertSeverity =
    configState === "offline"
      ? "warning"
      : configState === "degraded"
        ? "warning"
        : "info";

  return (
    <div className="surface-page">
      <Box
        className="glass-card"
        sx={{
          borderRadius: 5,
          p: { xs: 2, md: 2.5 },
          display: "grid",
          gap: 1.75,
        }}
      >
        <Stack
          direction={{ xs: "column", xl: "row" }}
          spacing={2}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", xl: "center" }}
        >
          <Box>
            <Typography variant="overline" sx={{ color: "#526173", letterSpacing: "0.16em" }}>
              {locale === "fr" ? "Réglages" : "Settings"}
            </Typography>
            <Typography variant="h5">{configCopy.title}</Typography>
            <Typography variant="body2" sx={{ color: "#667085", maxWidth: "64ch", mt: 0.75 }}>
              {configCopy.subtitle}
            </Typography>
          </Box>

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.25}>
            <Button variant="contained" onClick={() => void handleRefresh()} disabled={isRefreshing}>
              {isRefreshing ? configCopy.refreshingButton : configCopy.refreshButton}
            </Button>
          </Stack>
        </Stack>

        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          <Chip
            label={`${configCopy.source} · ${configPayload?.source ?? (locale === "fr" ? "hors ligne" : common.disabled.toLowerCase())}`}
            color={configPayload?.source === "tauri" ? "primary" : "default"}
            variant="outlined"
          />
          <Chip
            label={`${configCopy.privacy} · ${configPayload?.llm.privacyMode ?? "strict_local"}`}
            variant="outlined"
          />
          <Chip
            label={`${configCopy.copilot} · ${
              configPayload?.llm.enabled
                ? locale === "fr"
                  ? "activé"
                  : "enabled"
                : locale === "fr"
                  ? "désactivé"
                  : "disabled"
            }`}
            variant="outlined"
          />
        </Stack>

        <Alert severity={configAlertSeverity} variant="outlined">
          {statusMessage}
        </Alert>
      </Box>

      <InterfacePreferencesPanel
        locale={locale}
        activeLocale={locale}
        activeThemeMode={themeMode}
        onChangeLocale={setLocale}
        onChangeThemeMode={setThemeMode}
      />

      <Box
        sx={{
          mt: 2.5,
          display: "grid",
          gap: 2.5,
          gridTemplateColumns: {
            xs: "1fr",
            xl: "minmax(0, 1fr) minmax(360px, 0.96fr)",
          },
        }}
      >
        <PresetLibraryPanel
          locale={locale}
          packs={configPresetItems}
          activePackId={activePreset?.id ?? activePresetId}
          loading={isRefreshing}
          title={configCopy.presetsTitle}
          subtitle={configCopy.presetsSubtitle}
          onSelectPack={(packId) => {
            const preset = configPresetItems.find((item) => item.id === packId);
            setActivePresetId(packId);
            setStatusMessage(
              preset
                ? configCopy.selectedPreset(preset.name)
                : configCopy.selectedPreset(packId)
            );
          }}
          onRefresh={() => {
            void handleRefresh();
          }}
          onCreatePreset={() => {
            setStatusMessage(configCopy.stagedPreset);
          }}
          onOpenBenchmarks={() => {
            setStatusMessage(configCopy.stagedBench);
          }}
        />
        <OcrSettingsPanel
          locale={locale}
          enabledEngines={configPayload?.ocr.enabledEngines ?? DEFAULT_OCR_ENGINES}
          mode={configPayload?.ocr.mode ?? "consensus_amounts"}
          parallel={configPayload?.ocr.parallel ?? true}
          useGpu={configPayload?.ocr.useGpu ?? true}
          status={ocrStatus}
          onToggleEngine={(engine) => {
            const current = configPayload?.ocr.enabledEngines ?? DEFAULT_OCR_ENGINES;
            const next = current.includes(engine)
              ? current.filter((value) => value !== engine)
              : [...current, engine];
            void updateConfigOcr(
              { enabledEngines: next },
              locale === "fr"
                ? `Moteurs OCR: ${next.join(", ") || DEFAULT_OCR_ENGINES.join(", ")}`
                : `OCR engines: ${next.join(", ") || DEFAULT_OCR_ENGINES.join(", ")}`
            );
          }}
          onMoveEngine={(engine, direction) => {
            const current = [...(configPayload?.ocr.enabledEngines ?? DEFAULT_OCR_ENGINES)];
            const index = current.indexOf(engine);
            if (index === -1) {
              return;
            }
            const targetIndex = direction === "up" ? index - 1 : index + 1;
            if (targetIndex < 0 || targetIndex >= current.length) {
              return;
            }
            const next = [...current];
            const swap = next[targetIndex];
            next[targetIndex] = next[index];
            next[index] = swap;
            void updateConfigOcr(
              { enabledEngines: next },
              locale === "fr"
                ? `Priorité OCR: ${next.join(" > ")}`
                : `OCR priority: ${next.join(" > ")}`
            );
          }}
          onChangeMode={(mode) => {
            void updateConfigOcr(
              { mode },
              locale === "fr" ? `Mode OCR: ${mode}` : `OCR mode: ${mode}`
            );
          }}
          onToggleParallel={(parallel) => {
            void updateConfigOcr(
              { parallel },
              locale === "fr"
                ? `Exécution OCR ${parallel ? "parallèle" : "séquentielle"}`
                : `OCR execution ${parallel ? "parallel" : "sequential"}`
            );
          }}
          onToggleUseGpu={(useGpu) => {
            void updateConfigOcr(
              { useGpu },
              locale === "fr"
                ? `GPU OCR ${useGpu ? "activé" : "désactivé"}`
                : `OCR GPU ${useGpu ? "enabled" : "disabled"}`
            );
          }}
          onReset={() => {
            void updateConfigOcr(
              {
                enabledEngines: [...DEFAULT_OCR_ENGINES],
                mode: "consensus_amounts",
                parallel: true,
                useGpu: true,
              },
              locale === "fr" ? "OCR réinitialisé" : "OCR reset"
            );
          }}
        />
        <LlmSettingsPanel
          value={configPayload ? toPersistableConfigLabLlm(configPayload) : createDefaultLlmConfig()}
          disabled={!configPayload || isRefreshing}
          onChange={(nextConfig) => {
            void updateConfigLlm(
              nextConfig,
              locale === "fr" ? "Réglages LLM mis à jour" : "LLM settings updated"
            );
          }}
        />
        <RuntimeControlsPanel
          locale={locale}
          runtimeState={configState}
          runtimeLabel={
            configPayload
              ? `${configPayload.runtime.transport} · ${configPayload.runtime.endpoint || configPayload.source}`
              : locale === "fr"
                ? "En attente du payload runtime"
                : "Awaiting runtime payload"
          }
          backendLabel={
            activePreset?.name ??
            configPayload?.solver.selectedPresetId ??
            (locale === "fr" ? "Runtime local" : "Local runtime")
          }
          llmEnabled={configPayload?.llm.enabled ?? false}
          privacyMode={mapConfigPrivacyMode(configPayload?.llm.privacyMode ?? "strict_local")}
          benchmarkProfile={benchmarkProfile}
          benchmarkProfiles={["fast", "balanced", "deep"]}
          benchmarkEnabled={(configPayload?.benchmarks.length ?? 0) > 0}
          latencyLabel={
            configPayload
              ? `Budget ${configPayload.solver.timeBudgetMs} ms`
              : locale === "fr"
                ? "Budget en attente"
                : "Budget pending"
          }
          cacheLabel={
            configPayload
              ? `Cache ${configPayload.solver.cacheEnabled ? (locale === "fr" ? "on" : "on") : (locale === "fr" ? "off" : "off")}`
              : locale === "fr"
                ? "Cache en attente"
                : "Cache pending"
          }
          onToggleLlm={(enabled) => {
            void updateConfigLlm(
              { enabled },
              enabled ? configCopy.llmOn : configCopy.llmOff
            );
          }}
          onChangePrivacyMode={(mode) => {
            void updateConfigLlm(
              { privacyMode: mode as ConfigBridgePrivacyMode },
              configCopy.privacySet(mode)
            );
          }}
          onChangeBenchmarkProfile={(profile) => {
            setBenchmarkProfile(profile);
            setStatusMessage(configCopy.profileSet(profile));
          }}
          onRunDiagnostics={() => {
            setStatusMessage(configCopy.diagnostics);
          }}
          onRunBenchmarks={() => {
            setStatusMessage(configCopy.benchRun(benchmarkProfile));
          }}
        />
      </Box>

      <AutoAnnotatorPanel />
    </div>
  );
}
