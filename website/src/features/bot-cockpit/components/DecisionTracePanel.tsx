import type { ReactElement, ReactNode } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  Skeleton,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { alpha } from "@mui/material/styles";
import BoltRoundedIcon from "@mui/icons-material/BoltRounded";
import CloudOffRoundedIcon from "@mui/icons-material/CloudOffRounded";
import HelpOutlineRoundedIcon from "@mui/icons-material/HelpOutlineRounded";
import InsightsRoundedIcon from "@mui/icons-material/InsightsRounded";
import PlayCircleOutlineRoundedIcon from "@mui/icons-material/PlayCircleOutlineRounded";
import ReportProblemRoundedIcon from "@mui/icons-material/ReportProblemRounded";
import TimerRoundedIcon from "@mui/icons-material/TimerRounded";
import TrackChangesRoundedIcon from "@mui/icons-material/TrackChangesRounded";
import TrendingUpRoundedIcon from "@mui/icons-material/TrendingUpRounded";
import WarningAmberRoundedIcon from "@mui/icons-material/WarningAmberRounded";
import type { DecisionSnapshot, SpotSnapshot } from "../../llm/types";
import type { CockpitHistoryViewMode } from "../types";
import { getDecisionTraceCopy } from "../../../lib/workstationI18n";

export type DecisionTraceState = "idle" | "loading" | "ready" | "fallback" | "error";
type DecisionTraceLocale = "en" | "fr";

export interface DecisionTracePanelProps {
  state?: DecisionTraceState;
  decision?: DecisionSnapshot | null;
  spot?: SpotSnapshot | null;
  title?: string;
  subtitle?: string;
  emptyMessage?: string;
  fallbackMessage?: string;
  errorMessage?: string;
  loadingMessage?: string;
  locale?: DecisionTraceLocale;
  historyView?: CockpitHistoryViewMode;
  availableHistoryViews?: CockpitHistoryViewMode[];
  onHistoryViewChange?: (mode: CockpitHistoryViewMode) => void;
  onRetry?: () => void;
  sx?: SxProps<Theme>;
}

type StateTone = {
  label: string;
  color: "default" | "primary" | "secondary" | "success" | "warning" | "error";
  icon: ReactElement;
  description: string;
};

type DecisionTraceCopy = {
  defaultEmptyMessage: string;
  defaultFallbackMessage: string;
  defaultErrorMessage: string;
  defaultLoadingMessage: string;
  awaitingTrace: string;
  sourceUnknown: string;
  stateTracing: string;
  stateFallback: string;
  stateDegraded: string;
  stateReady: string;
  stateReadyWithSource: (source: string) => string;
  stateReadyDescription: string;
  stateIdle: string;
  cockpitLabel: string;
  sourceLabel: string;
  sourceNotReported: string;
  waitingLiveTrace: string;
  idleHelp: string;
  fallbackDecision: string;
  chosenAction: string;
  currentAction: string;
  heroEvInline: (value: string) => string;
  heroEvUnavailable: string;
  metricHeroEv: string;
  metricHeroEvHelper: string;
  metricExploitability: string;
  metricExploitabilityHelper: string;
    metricLatency: string;
    metricLatencyHelper: string;
    metricConfidence: string;
    metricConfidenceHelper: string;
    gateDecision: string;
    incidents: string;
    noIncidents: string;
    traceDetailsTitle: string;
  traceDetailsSubtitle: string;
  fallbackVisible: string;
  operatorReady: string;
  fallbackWithoutMix: string;
  noAlternativeRows: string;
  tableAction: string;
  tableFrequency: string;
  tableEv: string;
  tableSize: string;
  chosen: string;
  spotSource: string;
  noLiveSourceReported: string;
  potStack: string;
  warnings: string;
  warningCount: (count: number) => string;
  warningNone: string;
  retryTrace: string;
  historyRuntime: string;
  historyPersisted: string;
  historyCombined: string;
  localHistory: string;
  noLocalHistory: string;
};

const COPY: Record<DecisionTraceLocale, DecisionTraceCopy> = {
  fr: getDecisionTraceCopy("fr"),
  en: getDecisionTraceCopy("en"),
};

function formatPercent(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }

  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(normalized >= 10 ? 0 : 1)}%`;
}

function formatEv(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }

  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)} bb`;
}

function formatPot(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }

  return `${value.toFixed(value >= 10 ? 1 : 2)} bb`;
}

function formatMilliseconds(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }

  return `${Math.round(value)} ms`;
}

function formatGateDecision(decision?: DecisionSnapshot | null) {
  if (!decision?.gateDecision) {
    return "—";
  }
  return `${decision.gateDecision.allowed === false ? "blocked" : "allowed"} · ${decision.gateDecision.reason ?? "ready"}`;
}

function formatActionSize(value: number | null | undefined, locale: DecisionTraceLocale) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }

  if (value >= 10) {
    return `${value.toFixed(0)}% ${locale === "fr" ? "pot" : "pot"}`;
  }

  return `${value.toFixed(value < 1 ? 2 : 1)}x`;
}

function prettifyLabel(value?: string | null, fallback?: string) {
  if (!value) {
    return fallback ?? "—";
  }

  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function dedupeStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => typeof value === "string" && value.trim().length > 0)));
}

function getSourceLabel(source: DecisionSnapshot["source"] | null | undefined, locale: DecisionTraceLocale) {
  if (!source) {
    return COPY[locale].sourceUnknown;
  }

  switch (source) {
    case "native":
      return locale === "fr" ? "natif" : "native";
    case "http":
      return "http";
    case "fallback":
      return "fallback";
    case "legacy":
      return locale === "fr" ? "legacy" : "legacy";
    default:
      return source;
  }
}

function getStateTone(
  state: DecisionTraceState,
  decision: DecisionSnapshot | null | undefined,
  copy: DecisionTraceCopy,
  locale: DecisionTraceLocale
): StateTone {
  switch (state) {
    case "loading":
      return {
        label: copy.stateTracing,
        color: "secondary",
        icon: <PlayCircleOutlineRoundedIcon fontSize="small" />,
        description: copy.defaultLoadingMessage,
      };
    case "fallback":
      return {
        label: copy.stateFallback,
        color: "warning",
        icon: <CloudOffRoundedIcon fontSize="small" />,
        description: copy.defaultFallbackMessage,
      };
    case "error":
      return {
        label: copy.stateDegraded,
        color: "error",
        icon: <WarningAmberRoundedIcon fontSize="small" />,
        description: copy.defaultErrorMessage,
      };
    case "ready":
      return {
        label: decision?.source ? copy.stateReadyWithSource(getSourceLabel(decision.source, locale)) : copy.stateReady,
        color: "success",
        icon: <BoltRoundedIcon fontSize="small" />,
        description: copy.stateReadyDescription,
      };
    case "idle":
    default:
      return {
        label: copy.stateIdle,
        color: "default",
        icon: <HelpOutlineRoundedIcon fontSize="small" />,
        description: copy.defaultEmptyMessage,
      };
  }
}

function SummaryMetric({
  label,
  value,
  helper,
  icon,
}: {
  label: string;
  value: string;
  helper: string;
  icon: ReactNode;
}) {
  return (
    <Box
      sx={(theme) => ({
        minWidth: 0,
        flex: "1 1 180px",
        borderRadius: 3,
        border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
        background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
        px: 2,
        py: 1.75,
      })}
    >
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        <Box
          sx={(theme) => ({
            mt: 0.25,
            display: "grid",
            placeItems: "center",
            width: 34,
            height: 34,
            borderRadius: "50%",
            color: theme.palette.primary.main,
            bgcolor: alpha(theme.palette.primary.main, 0.12),
          })}
        >
          {icon}
        </Box>
        <Stack spacing={0.35} minWidth={0}>
          <Typography variant="caption" color="text.secondary">
            {label}
          </Typography>
          <Typography variant="h6">{value}</Typography>
          <Typography variant="body2" color="text.secondary">
            {helper}
          </Typography>
        </Stack>
      </Stack>
    </Box>
  );
}

function LoadingStateCard({ message }: { message: string }) {
  return (
    <Stack spacing={2.5}>
      <Box>
        <Skeleton variant="text" width="42%" height={34} />
        <Skeleton variant="text" width="78%" />
      </Box>
      <LinearProgress color="secondary" />
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
        {[0, 1, 2, 3].map((item) => (
          <Box
            key={item}
            sx={(theme) => ({
              flex: 1,
              p: 2,
              borderRadius: 3,
              border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
              backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
            })}
          >
            <Skeleton variant="text" width="46%" />
            <Skeleton variant="text" width="64%" height={34} />
            <Skeleton variant="text" width="72%" />
          </Box>
        ))}
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {message}
      </Typography>
    </Stack>
  );
}

export function DecisionTracePanel({
  state = "idle",
  decision = null,
  spot = null,
  title = "Decision trace",
  subtitle = "Track the chosen action, alternatives, latency, warnings, and source directly inside the cockpit.",
  emptyMessage,
  fallbackMessage,
  errorMessage,
  loadingMessage,
  locale = "en",
  historyView = "combined",
  availableHistoryViews = ["combined"],
  onHistoryViewChange,
  onRetry,
  sx,
}: DecisionTracePanelProps) {
  const copy = COPY[locale];
  const tone = getStateTone(state, decision, copy, locale);
  const warnings = decision?.warnings ?? [];
  const incidents = decision?.incidents ?? [];
  const incidentLabels = dedupeStrings(incidents.map((incident) => incident.label ?? incident.id).map((value) => prettifyLabel(value)));
  const actionHistory = dedupeStrings(spot?.actionHistory ?? []).slice(-4);
  const alternatives = [...(decision?.alternatives ?? [])].sort((left, right) => {
    const leftScore = left.frequency ?? -1;
    const rightScore = right.frequency ?? -1;
    return rightScore - leftScore;
  });
  const hasStructuredDecision = Boolean(decision?.chosenAction || alternatives.length > 0);
  const showEmptyState = state === "idle" && !hasStructuredDecision;
  const showFallback = state === "fallback";
  const showError = state === "error";
  const resolvedEmptyMessage = emptyMessage ?? copy.defaultEmptyMessage;
  const resolvedFallbackMessage = fallbackMessage ?? copy.defaultFallbackMessage;
  const resolvedErrorMessage = errorMessage ?? copy.defaultErrorMessage;
  const resolvedLoadingMessage = loadingMessage ?? copy.defaultLoadingMessage;
  const historyViewLabels: Record<CockpitHistoryViewMode, string> = {
    runtime: copy.historyRuntime,
    persisted: copy.historyPersisted,
    combined: copy.historyCombined,
  };

  return (
    <Card
      variant="outlined"
      sx={[
        (theme) => ({
          borderRadius: 5,
          overflow: "hidden",
          borderColor: alpha(theme.palette.text.primary, 0.08),
          background: theme.palette.background.paper,
          boxShadow:
            theme.palette.mode === "dark"
              ? "0 18px 44px rgba(0, 0, 0, 0.28)"
              : "0 10px 30px rgba(15, 23, 42, 0.06)",
        }),
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
    >
      <CardContent sx={{ p: { xs: 2.25, md: 3 } }}>
        <Stack spacing={2.5}>
          <Stack
            direction={{ xs: "column", lg: "row" }}
            spacing={2}
            justifyContent="space-between"
            alignItems={{ xs: "flex-start", lg: "center" }}
          >
            <Box>
              <Typography variant="overline" color="text.secondary">
                {copy.cockpitLabel}
              </Typography>
              <Typography variant="h5">{title}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 820, mt: 0.5 }}>
                {subtitle}
              </Typography>
            </Box>

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip
                icon={tone.icon}
                label={tone.label}
                color={tone.color}
                variant={tone.color === "default" ? "outlined" : "filled"}
              />
              {decision?.source ? (
                <Chip
                  label={`${copy.sourceLabel}: ${getSourceLabel(decision.source, locale)}`}
                  variant="outlined"
                  sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                />
              ) : null}
              {spot?.street ? (
                <Chip
                  label={prettifyLabel(spot.street)}
                  variant="outlined"
                  sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                />
              ) : null}
            </Stack>
          </Stack>

          {state === "loading" ? (
            <LoadingStateCard message={resolvedLoadingMessage} />
          ) : showEmptyState ? (
            <Stack spacing={1.5}>
              <Chip
                icon={<TrackChangesRoundedIcon fontSize="small" />}
                label={copy.waitingLiveTrace}
                variant="outlined"
                sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
              />
              <Typography variant="body1">{resolvedEmptyMessage}</Typography>
              <Typography variant="body2" color="text.secondary">
                {copy.idleHelp}
              </Typography>
            </Stack>
          ) : (
            <>
              <Stack direction={{ xs: "column", xl: "row" }} spacing={1.5}>
                <Box
                  sx={(theme) => ({
                    flex: "1.2 1 0%",
                    borderRadius: 4,
                    border: `1px solid ${alpha(theme.palette.primary.main, 0.22)}`,
                    background: alpha(theme.palette.primary.main, 0.06),
                    px: 2.5,
                    py: 2.2,
                  })}
                >
                  <Stack spacing={1.25}>
                    <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
                      <Chip
                        label={showFallback ? copy.fallbackDecision : copy.chosenAction}
                        color={showFallback ? "warning" : "success"}
                        size="small"
                      />
                      {decision?.source ? (
                        <Chip
                          label={getSourceLabel(decision.source, locale)}
                          size="small"
                          variant="outlined"
                        />
                      ) : null}
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      {copy.currentAction}
                    </Typography>
                    <Typography variant="h4" sx={{ letterSpacing: "-0.04em" }}>
                      {prettifyLabel(decision?.chosenAction, copy.awaitingTrace)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {decision?.heroEv != null
                        ? copy.heroEvInline(formatEv(decision.heroEv))
                        : copy.heroEvUnavailable}
                    </Typography>
                  </Stack>
                </Box>

                <SummaryMetric
                  label={copy.metricHeroEv}
                  value={formatEv(decision?.heroEv)}
                  helper={copy.metricHeroEvHelper}
                  icon={<TrendingUpRoundedIcon fontSize="small" />}
                />
                <SummaryMetric
                  label={copy.metricExploitability}
                  value={formatEv(decision?.exploitability)}
                  helper={copy.metricExploitabilityHelper}
                  icon={<InsightsRoundedIcon fontSize="small" />}
                />
                <SummaryMetric
                  label={copy.metricLatency}
                  value={formatMilliseconds(decision?.latencyMs)}
                  helper={
                    decision?.source
                      ? `${copy.sourceLabel}: ${getSourceLabel(decision.source, locale)}`
                      : copy.sourceNotReported
                  }
                  icon={<TimerRoundedIcon fontSize="small" />}
                />
                <SummaryMetric
                  label={copy.metricConfidence}
                  value={formatPercent(decision?.gateDecision?.confidence ?? decision?.confidence)}
                  helper={copy.metricConfidenceHelper}
                  icon={<TrackChangesRoundedIcon fontSize="small" />}
                />
              </Stack>

              <Divider />

              <Stack spacing={1.5}>
                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  spacing={1}
                  justifyContent="space-between"
                  alignItems={{ xs: "flex-start", sm: "center" }}
                >
                  <Box>
                    <Typography variant="h6">{copy.traceDetailsTitle}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {copy.traceDetailsSubtitle}
                    </Typography>
                  </Box>
                  <Tooltip title={tone.description}>
                    <Chip
                      label={showFallback ? copy.fallbackVisible : copy.operatorReady}
                      variant="outlined"
                      sx={{ borderColor: "rgba(16,24,40,0.12)" }}
                    />
                  </Tooltip>
                </Stack>

                {warnings.length > 0 ? (
                  <Stack spacing={1}>
                    {warnings.map((warning, index) => (
                      <Alert
                        key={`${warning}-${index}`}
                        severity={showError ? "error" : "warning"}
                        variant="outlined"
                        icon={<ReportProblemRoundedIcon fontSize="small" />}
                      >
                        {prettifyLabel(warning)}
                      </Alert>
                    ))}
                  </Stack>
                ) : null}

                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" },
                    gap: 1.5,
                  }}
                >
                  <Box
                    sx={(theme) => ({
                      borderRadius: 3,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
                      px: 2,
                      py: 1.5,
                    })}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {copy.gateDecision}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      {formatGateDecision(decision)}
                    </Typography>
                  </Box>
                  <Box
                    sx={(theme) => ({
                      borderRadius: 3,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
                      px: 2,
                      py: 1.5,
                    })}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {copy.incidents}
                    </Typography>
                    {incidentLabels.length > 0 ? (
                      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
                        {incidentLabels.map((incident) => (
                          <Chip key={incident} label={incident} size="small" color="error" variant="outlined" />
                        ))}
                      </Stack>
                    ) : (
                      <Typography variant="body2" sx={{ mt: 0.5 }}>
                        {copy.noIncidents}
                      </Typography>
                    )}
                  </Box>
                  <Box
                    sx={(theme) => ({
                      borderRadius: 3,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
                      px: 2,
                      py: 1.5,
                    })}
                  >
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      spacing={1}
                      justifyContent="space-between"
                      alignItems={{ xs: "flex-start", sm: "center" }}
                    >
                      <Typography variant="caption" color="text.secondary">
                        {copy.localHistory}
                      </Typography>
                      {availableHistoryViews.length > 1 ? (
                        <ToggleButtonGroup
                          size="small"
                          exclusive
                          value={historyView}
                          onChange={(_, value: CockpitHistoryViewMode | null) => {
                            if (value && onHistoryViewChange) {
                              onHistoryViewChange(value);
                            }
                          }}
                        >
                          {availableHistoryViews.map((mode) => (
                            <ToggleButton key={mode} value={mode} sx={{ px: 1, py: 0.25, textTransform: "none" }}>
                              {historyViewLabels[mode]}
                            </ToggleButton>
                          ))}
                        </ToggleButtonGroup>
                      ) : null}
                    </Stack>
                    {actionHistory.length > 0 ? (
                      <Stack spacing={0.5} sx={{ mt: 0.75 }}>
                        {actionHistory.map((entry, index) => (
                          <Typography key={`${entry}-${index}`} variant="body2" color="text.secondary">
                            {index + 1}. {prettifyLabel(entry)}
                          </Typography>
                        ))}
                      </Stack>
                    ) : (
                      <Typography variant="body2" sx={{ mt: 0.5 }}>
                        {copy.noLocalHistory}
                      </Typography>
                    )}
                  </Box>
                </Box>

                {showFallback ? (
                  <Alert severity="info" variant="outlined" icon={<CloudOffRoundedIcon fontSize="small" />}>
                    {resolvedFallbackMessage}
                  </Alert>
                ) : null}

                {showError ? (
                  <Alert severity="error" variant="outlined" icon={<WarningAmberRoundedIcon fontSize="small" />}>
                    {resolvedErrorMessage}
                  </Alert>
                ) : null}

                {alternatives.length === 0 ? (
                  <Alert severity={showFallback ? "info" : "warning"} variant="outlined">
                    {showFallback ? copy.fallbackWithoutMix : copy.noAlternativeRows}
                  </Alert>
                ) : (
                  <Box
                    sx={(theme) => ({
                      borderRadius: 4,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      overflow: "hidden",
                      bgcolor: theme.palette.background.paper,
                    })}
                  >
                    <Box
                      sx={(theme) => ({
                        display: "grid",
                        gridTemplateColumns: {
                          xs: "minmax(0, 1.5fr) 90px 88px",
                          md: "minmax(0, 1.5fr) 120px 110px 96px",
                        },
                        gap: 1.5,
                        px: 2,
                        py: 1.25,
                        borderBottom: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                        bgcolor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
                      })}
                    >
                      <Typography variant="caption" color="text.secondary">
                        {copy.tableAction}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {copy.tableFrequency}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {copy.tableEv}
                      </Typography>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: { xs: "none", md: "block" } }}
                      >
                        {copy.tableSize}
                      </Typography>
                    </Box>

                    {alternatives.map((action, index) => {
                      const isChosen = action.name === decision?.chosenAction;
                      const progressValue = (() => {
                        if (action.frequency == null || Number.isNaN(action.frequency)) {
                          return 0;
                        }

                        const normalized = Math.abs(action.frequency) <= 1 ? action.frequency * 100 : action.frequency;
                        return Math.max(0, Math.min(100, normalized));
                      })();

                      return (
                        <Box
                          key={`${action.name}-${index}`}
                          sx={(theme) => ({
                            display: "grid",
                            gridTemplateColumns: {
                              xs: "minmax(0, 1.5fr) 90px 88px",
                              md: "minmax(0, 1.5fr) 120px 110px 96px",
                            },
                            gap: 1.5,
                            alignItems: "center",
                            px: 2,
                            py: 1.5,
                            borderBottom:
                              index === alternatives.length - 1
                                ? "none"
                                : `1px solid ${alpha(theme.palette.text.primary, 0.06)}`,
                            bgcolor: isChosen ? alpha(theme.palette.primary.main, 0.08) : "transparent",
                          })}
                        >
                          <Stack spacing={0.85} minWidth={0}>
                            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                              <Typography variant="body1" sx={{ fontWeight: 700 }}>
                                {prettifyLabel(action.name)}
                              </Typography>
                              {isChosen ? <Chip size="small" color="primary" label={copy.chosen} /> : null}
                            </Stack>
                            <Box sx={{ minWidth: 0 }}>
                              <LinearProgress
                                variant="determinate"
                                value={progressValue}
                                color={isChosen ? "primary" : "secondary"}
                                sx={(theme) => ({
                                  height: 8,
                                  borderRadius: 99,
                                  bgcolor: alpha(theme.palette.text.primary, 0.12),
                                })}
                              />
                            </Box>
                          </Stack>

                          <Typography variant="body2" sx={{ fontVariantNumeric: "tabular-nums" }}>
                            {formatPercent(action.frequency)}
                          </Typography>
                          <Typography
                            variant="body2"
                            sx={{
                              fontVariantNumeric: "tabular-nums",
                              color:
                                (action.ev ?? 0) > 0
                                  ? "success.main"
                                  : (action.ev ?? 0) < 0
                                    ? "error.main"
                                    : "text.primary",
                            }}
                          >
                            {formatEv(action.ev)}
                          </Typography>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{
                              display: { xs: "none", md: "block" },
                              fontVariantNumeric: "tabular-nums",
                            }}
                          >
                            {formatActionSize(action.size, locale)}
                          </Typography>
                        </Box>
                      );
                    })}
                  </Box>
                )}

                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" },
                    gap: 1.5,
                    mt: 0.25,
                  }}
                >
                  <Box
                    sx={(theme) => ({
                      borderRadius: 3,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
                      px: 2,
                      py: 1.5,
                    })}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {copy.spotSource}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      {spot?.source ? prettifyLabel(spot.source) : copy.noLiveSourceReported}
                    </Typography>
                  </Box>
                  <Box
                    sx={(theme) => ({
                      borderRadius: 3,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
                      px: 2,
                      py: 1.5,
                    })}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {copy.potStack}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      {formatPot(spot?.pot)} / {formatPot(spot?.effectiveStack)}
                    </Typography>
                  </Box>
                  <Box
                    sx={(theme) => ({
                      borderRadius: 3,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
                      px: 2,
                      py: 1.5,
                    })}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {copy.warnings}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      {warnings.length > 0 ? copy.warningCount(warnings.length) : copy.warningNone}
                    </Typography>
                  </Box>
                </Box>

                {onRetry ? (
                  <Stack direction="row" justifyContent="flex-end">
                    <Button
                      onClick={onRetry}
                      variant="outlined"
                      startIcon={<BoltRoundedIcon />}
                      sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                    >
                      {copy.retryTrace}
                    </Button>
                  </Stack>
                ) : null}
              </Stack>
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

export default DecisionTracePanel;
