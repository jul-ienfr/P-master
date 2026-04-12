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
  Tooltip,
  Typography,
} from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { alpha } from "@mui/material/styles";
import AutoGraphRoundedIcon from "@mui/icons-material/AutoGraphRounded";
import BoltRoundedIcon from "@mui/icons-material/BoltRounded";
import CachedRoundedIcon from "@mui/icons-material/CachedRounded";
import CloudOffRoundedIcon from "@mui/icons-material/CloudOffRounded";
import HelpOutlineRoundedIcon from "@mui/icons-material/HelpOutlineRounded";
import InsightsRoundedIcon from "@mui/icons-material/InsightsRounded";
import PlayCircleOutlineRoundedIcon from "@mui/icons-material/PlayCircleOutlineRounded";
import ReportProblemRoundedIcon from "@mui/icons-material/ReportProblemRounded";
import WarningAmberRoundedIcon from "@mui/icons-material/WarningAmberRounded";

export type SolveResultsState =
  | "idle"
  | "loading"
  | "ready"
  | "unsupported"
  | "offline_safe"
  | "error";

export interface SolveActionResult {
  name: string;
  label?: string;
  size?: number | null;
  frequency?: number | null;
  ev?: number | null;
  isRecommended?: boolean;
}

export interface SolveResultsData {
  chosenAction?: string | null;
  actions?: SolveActionResult[];
  heroEv?: number | null;
  exploitability?: number | null;
  cacheHit?: boolean | null;
  elapsedMs?: number | null;
  presetId?: string | null;
  warnings?: string[];
  confidence?: number | null;
  fallbackReason?: string | null;
  incidents?: Array<{
    id: string;
    severity?: "info" | "warning" | "error";
    label?: string;
  }>;
  gateDecision?: {
    allowed?: boolean;
    reason?: string;
    confidence?: number;
  };
}

export interface SolveResultsPanelProps {
  state?: SolveResultsState;
  result?: SolveResultsData | null;
  title?: string;
  subtitle?: string;
  emptyMessage?: string;
  unsupportedMessage?: string;
  offlineMessage?: string;
  errorMessage?: string;
  loadingMessage?: string;
  onRetry?: () => void;
  sx?: SxProps<Theme>;
  locale?: "en" | "fr";
}

type SolveResultsCopy = {
  defaults: {
    emptyMessage: string;
    unsupportedMessage: string;
    offlineMessage: string;
    errorMessage: string;
    loadingMessage: string;
  };
  state: {
    solving: string;
    unsupported: string;
    offline: string;
    degraded: string;
    ready: string;
    readyCached: string;
    idle: string;
  };
      text: {
    shellLabel: string;
    preset: string;
    cacheHit: string;
    cacheMiss: string;
    retry: string;
    waiting: string;
    waitingDescription: string;
    fallbackRecommendation: string;
    primaryRecommendation: string;
    recommended: string;
    chosen: string;
    chosenAction: string;
    noSizing: string;
    sizingSignal: (value: string) => string;
    heroEv: string;
    heroEvHelper: string;
    exploitability: string;
    exploitabilityHelper: string;
        elapsed: string;
        elapsedCached: string;
        elapsedFresh: string;
        confidence: string;
        confidenceHelper: string;
        gateDecision: string;
        incidents: string;
        noIncidents: string;
        actionMix: string;
    actionMixSubtitle: string;
    fallbackVisible: string;
    operatorReady: string;
    offlineNoRows: string;
    noRows: string;
    columns: {
      action: string;
      frequency: string;
      ev: string;
      size: string;
    };
  };
  descriptions: {
    loading: string;
    unsupported: string;
    offline: string;
    error: string;
    ready: string;
  };
};

const SOLVE_RESULTS_COPY: Record<"en" | "fr", SolveResultsCopy> = {
  en: {
    defaults: {
      emptyMessage: "No result yet. Launch a solve to inspect the action mix.",
      unsupportedMessage: "This spot is outside the current deterministic path.",
      offlineMessage: "Offline-safe fallback is active.",
      errorMessage: "The last solve did not complete correctly.",
      loadingMessage: "Waiting for a structured /v2/solve response.",
    },
    state: {
      solving: "Solving",
      unsupported: "Limited",
      offline: "Offline-safe",
      degraded: "Error",
      ready: "Ready",
      readyCached: "Ready · cached",
      idle: "Idle",
    },
    text: {
      shellLabel: "Solver",
      preset: "Preset",
      cacheHit: "Cache hit",
      cacheMiss: "Cache miss",
      retry: "Retry",
      waiting: "Waiting for /v2/solve",
      waitingDescription: "Safe to keep visible even when the local runtime is offline.",
      fallbackRecommendation: "Fallback recommendation",
      primaryRecommendation: "Primary recommendation",
      recommended: "Recommended",
      chosen: "Chosen",
      chosenAction: "Chosen action",
      noSizing: "No sizing provided.",
      sizingSignal: (value) => `Sizing: ${value}`,
      heroEv: "Hero EV",
      heroEvHelper: "Expected value for this node.",
      exploitability: "Exploitability",
      exploitabilityHelper: "Lower is better.",
        elapsed: "Elapsed",
        elapsedCached: "Cache reused.",
        elapsedFresh: "Fresh solve or fallback.",
        confidence: "Confidence",
        confidenceHelper: "Operator-visible confidence on the returned recommendation.",
        gateDecision: "Gate decision",
        incidents: "Incidents",
        noIncidents: "No recorded incident.",
        actionMix: "Action mix",
      actionMixSubtitle: "Frequency, EV and size for each returned action.",
      fallbackVisible: "Fallback visible",
      operatorReady: "Ready",
      offlineNoRows: "The offline-safe path returned no action rows.",
      noRows: "The solve completed without structured action rows.",
      columns: {
        action: "Action",
        frequency: "Frequency",
        ev: "EV",
        size: "Size",
      },
    },
    descriptions: {
      loading: "The solver is evaluating the current spot.",
      unsupported: "The spot is visible but not fully supported.",
      offline: "The UI stays usable while the runtime is unavailable.",
      error: "Check the warnings and retry.",
      ready: "Structured solver output is available.",
    },
  },
  fr: {
    defaults: {
      emptyMessage: "Aucun résultat pour l’instant. Lance un solve pour voir le mix d’actions.",
      unsupportedMessage: "Ce spot sort du chemin déterministe actuellement pris en charge.",
      offlineMessage: "Le fallback hors ligne est actif.",
      errorMessage: "Le dernier solve ne s’est pas terminé correctement.",
      loadingMessage: "En attente d’une réponse structurée de /v2/solve.",
    },
    state: {
      solving: "Calcul",
      unsupported: "Limité",
      offline: "Hors ligne",
      degraded: "Erreur",
      ready: "Prêt",
      readyCached: "Prêt · cache",
      idle: "Vide",
    },
    text: {
      shellLabel: "Solver",
      preset: "Preset",
      cacheHit: "Cache touché",
      cacheMiss: "Cache manqué",
      retry: "Relancer",
      waiting: "En attente de /v2/solve",
      waitingDescription: "Le panneau reste affichable même si le runtime local est indisponible.",
      fallbackRecommendation: "Reco fallback",
      primaryRecommendation: "Reco principale",
      recommended: "Recommandée",
      chosen: "Retenue",
      chosenAction: "Action retenue",
      noSizing: "Aucune taille fournie.",
      sizingSignal: (value) => `Sizing : ${value}`,
      heroEv: "EV hero",
      heroEvHelper: "Valeur attendue sur ce nœud.",
      exploitability: "Exploitabilité",
      exploitabilityHelper: "Plus bas = mieux.",
        elapsed: "Temps",
        elapsedCached: "Cache réutilisé.",
        elapsedFresh: "Solve frais ou fallback.",
        confidence: "Confiance",
        confidenceHelper: "Niveau de confiance visible par l’opérateur sur la recommandation.",
        gateDecision: "Décision du gate",
        incidents: "Incidents",
        noIncidents: "Aucun incident remonté.",
        actionMix: "Mix d’actions",
      actionMixSubtitle: "Fréquence, EV et taille pour chaque action renvoyée.",
      fallbackVisible: "Fallback visible",
      operatorReady: "Prêt",
      offlineNoRows: "Le chemin hors ligne n’a renvoyé aucune ligne d’action.",
      noRows: "Le solve s’est terminé sans lignes d’action structurées.",
      columns: {
        action: "Action",
        frequency: "Fréquence",
        ev: "EV",
        size: "Taille",
      },
    },
    descriptions: {
      loading: "Le solver évalue le spot en cours.",
      unsupported: "Le spot reste visible mais n’est pas totalement pris en charge.",
      offline: "L’UI reste utilisable même si le runtime est indisponible.",
      error: "Vérifie les alertes puis relance.",
      ready: "La sortie structurée du solver est disponible.",
    },
  },
};

type StateTone = {
  label: string;
  color: "default" | "primary" | "secondary" | "success" | "warning" | "error";
  icon: ReactElement;
  description: string;
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

function formatMilliseconds(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }

  return `${Math.round(value)} ms`;
}

function formatSize(value?: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }

  if (value >= 10) {
    return `${value.toFixed(0)}% pot`;
  }

  return `${value.toFixed(value < 1 ? 2 : 1)}x`;
}

function prettifyActionLabel(action: SolveActionResult | undefined, chosenAction?: string | null) {
  const raw = action?.label || action?.name || chosenAction || "";
  if (!raw) {
    return "Awaiting result";
  }

  return raw
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function normalizeWarning(warning: string) {
  return warning
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatGateLabel(result?: SolveResultsData | null) {
  const gate = result?.gateDecision;
  if (!gate) {
    return "—";
  }
  return `${gate.allowed === false ? "blocked" : "allowed"} · ${gate.reason ?? "ready"}`;
}

function pickChosenAction(result?: SolveResultsData | null) {
  if (!result) {
    return undefined;
  }

  const fromName = result.actions?.find(
    (action) =>
      action.name === result.chosenAction ||
      action.label === result.chosenAction ||
      action.isRecommended === true
  );

  if (fromName) {
    return fromName;
  }

  return [...(result.actions ?? [])].sort((left, right) => {
    const leftScore = left.frequency ?? -1;
    const rightScore = right.frequency ?? -1;
    return rightScore - leftScore;
  })[0];
}

function getStateTone(
  state: SolveResultsState,
  result: SolveResultsData | null | undefined,
  copy: SolveResultsCopy
): StateTone {
  switch (state) {
    case "loading":
      return {
        label: copy.state.solving,
        color: "secondary",
        icon: <PlayCircleOutlineRoundedIcon fontSize="small" />,
        description: copy.descriptions.loading,
      };
    case "unsupported":
      return {
        label: copy.state.unsupported,
        color: "warning",
        icon: <ReportProblemRoundedIcon fontSize="small" />,
        description: copy.descriptions.unsupported,
      };
    case "offline_safe":
      return {
        label: copy.state.offline,
        color: "primary",
        icon: <CloudOffRoundedIcon fontSize="small" />,
        description: copy.descriptions.offline,
      };
    case "error":
      return {
        label: copy.state.degraded,
        color: "error",
        icon: <WarningAmberRoundedIcon fontSize="small" />,
        description: copy.descriptions.error,
      };
    case "ready":
      return {
        label: result?.cacheHit ? copy.state.readyCached : copy.state.ready,
        color: "success",
        icon: <BoltRoundedIcon fontSize="small" />,
        description: copy.descriptions.ready,
      };
    case "idle":
    default:
      return {
        label: copy.state.idle,
        color: "default",
        icon: <HelpOutlineRoundedIcon fontSize="small" />,
        description: copy.defaults.emptyMessage,
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
        background:
          theme.palette.mode === "dark"
            ? "linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02))"
            : "linear-gradient(180deg, rgba(16,24,40,0.03), rgba(16,24,40,0.015))",
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
            })}
          >
            <Skeleton variant="text" width="46%" />
            <Skeleton variant="text" width="64%" height={34} />
            <Skeleton variant="text" width="72%" />
          </Box>
        ))}
      </Stack>
      <Box
        sx={(theme) => ({
          borderRadius: 3,
          border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
          overflow: "hidden",
        })}
      >
        {[0, 1, 2, 3].map((row) => (
          <Box
            key={row}
            sx={(theme) => ({
              px: 2,
              py: 1.5,
              borderBottom:
                row === 3 ? "none" : `1px solid ${alpha(theme.palette.text.primary, 0.06)}`,
            })}
          >
            <Stack direction="row" spacing={2} alignItems="center">
              <Skeleton variant="text" width="22%" />
              <Skeleton variant="rounded" width="30%" height={8} />
              <Skeleton variant="text" width="14%" />
              <Skeleton variant="text" width="14%" />
            </Stack>
          </Box>
        ))}
      </Box>
      <Typography variant="body2" color="text.secondary">
        {message}
      </Typography>
    </Stack>
  );
}

export function SolveResultsPanel({
  state = "idle",
  result = null,
  title = "Solve results",
  subtitle = "Read the current recommendation, compare action frequencies, and keep fallback states visible.",
  emptyMessage,
  unsupportedMessage,
  offlineMessage,
  errorMessage,
  loadingMessage,
  onRetry,
  sx,
  locale = "en",
}: SolveResultsPanelProps) {
  const copy = SOLVE_RESULTS_COPY[locale];
  const tone = getStateTone(state, result, copy);
  const chosen = pickChosenAction(result);
  const warnings = result?.warnings ?? [];
  const incidents = result?.incidents ?? [];
  const resolvedEmptyMessage = emptyMessage ?? copy.defaults.emptyMessage;
  const resolvedUnsupportedMessage = unsupportedMessage ?? copy.defaults.unsupportedMessage;
  const resolvedOfflineMessage = offlineMessage ?? copy.defaults.offlineMessage;
  const resolvedErrorMessage = errorMessage ?? copy.defaults.errorMessage;
  const resolvedLoadingMessage = loadingMessage ?? copy.defaults.loadingMessage;
  const actions = [...(result?.actions ?? [])].sort((left, right) => {
    const recommendedDelta = Number(right.isRecommended) - Number(left.isRecommended);
    if (recommendedDelta !== 0) {
      return recommendedDelta;
    }

    return (right.frequency ?? -1) - (left.frequency ?? -1);
  });

  const hasStructuredResults = actions.length > 0 || Boolean(result?.chosenAction);
  const showEmptyState = state === "idle" && !hasStructuredResults;
  const showUnsupported = state === "unsupported";
  const showOffline = state === "offline_safe";
  const showError = state === "error";

  return (
    <Card
      variant="outlined"
      sx={[
        (theme) => ({
          borderRadius: 5,
          overflow: "hidden",
          borderColor: alpha(theme.palette.text.primary, 0.08),
          background: `
            radial-gradient(circle at top right, ${alpha(theme.palette.primary.main, 0.14)}, transparent 32%),
            radial-gradient(circle at bottom left, ${alpha(theme.palette.secondary.main, 0.12)}, transparent 28%),
            ${
              theme.palette.mode === "dark"
                ? "linear-gradient(180deg, rgba(9,16,27,0.96), rgba(8,13,22,0.94))"
                : "linear-gradient(180deg, rgba(255,255,255,0.96), rgba(247,249,252,0.98))"
            }
          `,
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
                {copy.text.shellLabel}
              </Typography>
              <Typography variant="h5">{title}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 780, mt: 0.5 }}>
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
                {result?.presetId ? (
                  <Chip
                    label={`${copy.text.preset} · ${result.presetId}`}
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                  />
                ) : null}
              <Chip
                icon={<CachedRoundedIcon fontSize="small" />}
                label={result?.cacheHit ? copy.text.cacheHit : copy.text.cacheMiss}
                color={result?.cacheHit ? "success" : "default"}
                variant={result?.cacheHit ? "filled" : "outlined"}
              />
            </Stack>
          </Stack>

          {state === "loading" ? (
            <LoadingStateCard message={resolvedLoadingMessage} />
          ) : (
            <>
              {(showUnsupported || showOffline || showError || warnings.length > 0) && (
                <Stack spacing={1.25}>
                  {showUnsupported ? (
                    <Alert severity="warning" variant="outlined">
                      {resolvedUnsupportedMessage}
                    </Alert>
                  ) : null}
                  {showOffline ? (
                    <Alert severity="info" variant="outlined">
                      {resolvedOfflineMessage}
                    </Alert>
                  ) : null}
                  {showError ? (
                    <Alert
                      severity="error"
                      variant="outlined"
                      action={
                        onRetry ? (
                          <Button color="inherit" size="small" onClick={onRetry}>
                            {copy.text.retry}
                          </Button>
                        ) : undefined
                      }
                    >
                      {resolvedErrorMessage}
                    </Alert>
                  ) : null}
                  {warnings.map((warning) => (
                    <Alert key={warning} severity="warning" variant="outlined">
                      {normalizeWarning(warning)}
                    </Alert>
                  ))}
                </Stack>
              )}

              {showEmptyState ? (
                <Stack
                  spacing={2}
                  alignItems="flex-start"
                  sx={(theme) => ({
                    p: 2.5,
                    borderRadius: 4,
                    border: `1px dashed ${alpha(theme.palette.text.primary, 0.14)}`,
                    bgcolor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.02 : 0.01),
                  })}
                >
                  <Chip
                    icon={<InsightsRoundedIcon fontSize="small" />}
                    label={copy.text.waiting}
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                  />
                  <Typography variant="body1">{resolvedEmptyMessage}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {copy.text.waitingDescription}
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
                        background: `
                          radial-gradient(circle at top right, ${alpha(theme.palette.primary.main, 0.22)}, transparent 38%),
                          linear-gradient(180deg, ${alpha(theme.palette.primary.main, 0.08)}, ${alpha(
                            theme.palette.text.primary,
                            theme.palette.mode === "dark" ? 0.02 : 0.01
                          )})
                        `,
                        px: 2.5,
                        py: 2.2,
                      })}
                    >
                      <Stack spacing={1.25}>
                        <Stack direction="row" alignItems="center" spacing={1}>
                          <Chip
                            label={
                              showOffline
                                ? copy.text.fallbackRecommendation
                                : copy.text.primaryRecommendation
                            }
                            color={showOffline ? "primary" : "success"}
                            size="small"
                          />
                          {chosen?.isRecommended ? (
                            <Chip
                              label={copy.text.recommended}
                              color="success"
                              size="small"
                              variant="outlined"
                            />
                          ) : null}
                        </Stack>
                        <Typography variant="caption" color="text.secondary">
                          {copy.text.chosenAction}
                        </Typography>
                        <Typography variant="h4" sx={{ letterSpacing: "-0.04em" }}>
                          {prettifyActionLabel(chosen, result?.chosenAction)}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {chosen?.size != null
                            ? copy.text.sizingSignal(formatSize(chosen.size))
                            : copy.text.noSizing}
                        </Typography>
                      </Stack>
                    </Box>

                    <SummaryMetric
                      label={copy.text.heroEv}
                      value={formatEv(result?.heroEv)}
                      helper={copy.text.heroEvHelper}
                      icon={<AutoGraphRoundedIcon fontSize="small" />}
                    />
                    <SummaryMetric
                      label={copy.text.exploitability}
                      value={formatEv(result?.exploitability)}
                      helper={copy.text.exploitabilityHelper}
                      icon={<InsightsRoundedIcon fontSize="small" />}
                    />
                    <SummaryMetric
                      label={copy.text.elapsed}
                      value={formatMilliseconds(result?.elapsedMs)}
                      helper={result?.cacheHit ? copy.text.elapsedCached : copy.text.elapsedFresh}
                      icon={<BoltRoundedIcon fontSize="small" />}
                    />
                    <SummaryMetric
                      label={copy.text.confidence}
                      value={formatPercent(result?.gateDecision?.confidence ?? result?.confidence)}
                      helper={copy.text.confidenceHelper}
                      icon={<InsightsRoundedIcon fontSize="small" />}
                    />
                  </Stack>

                  <Divider />

                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    <Chip
                      label={`${copy.text.gateDecision} · ${formatGateLabel(result)}`}
                      color={result?.gateDecision?.allowed === false ? "warning" : "success"}
                      variant="outlined"
                    />
                    {result?.fallbackReason ? (
                      <Chip label={`Fallback · ${normalizeWarning(result.fallbackReason)}`} color="info" variant="outlined" />
                    ) : null}
                  </Stack>

                  {incidents.length > 0 ? (
                    <Stack spacing={1}>
                      {incidents.map((incident) => (
                        <Alert
                          key={incident.id}
                          severity={incident.severity === "error" ? "error" : incident.severity === "warning" ? "warning" : "info"}
                          variant="outlined"
                        >
                          {incident.label ?? normalizeWarning(incident.id)}
                        </Alert>
                      ))}
                    </Stack>
                  ) : (
                    <Alert severity="success" variant="outlined">
                      {copy.text.noIncidents}
                    </Alert>
                  )}

                  <Stack spacing={1.5}>
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      spacing={1}
                      justifyContent="space-between"
                      alignItems={{ xs: "flex-start", sm: "center" }}
                    >
                      <Box>
                        <Typography variant="h6">{copy.text.actionMix}</Typography>
                        <Typography variant="body2" color="text.secondary">
                          {copy.text.actionMixSubtitle}
                        </Typography>
                      </Box>
                      <Tooltip title={tone.description}>
                        <Chip
                          label={showOffline ? copy.text.fallbackVisible : copy.text.operatorReady}
                          variant="outlined"
                          sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                        />
                      </Tooltip>
                    </Stack>

                    {actions.length === 0 ? (
                      <Alert severity={showOffline ? "info" : "warning"} variant="outlined">
                        {showOffline ? copy.text.offlineNoRows : copy.text.noRows}
                      </Alert>
                    ) : (
                      <Box
                        sx={(theme) => ({
                          borderRadius: 4,
                          border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                          overflow: "hidden",
                          bgcolor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.02 : 0.01),
                        })}
                      >
                        <Box
                          sx={(theme) => ({
                            display: "grid",
                            gridTemplateColumns: { xs: "minmax(0, 1.5fr) 92px 84px", md: "minmax(0, 1.5fr) 132px 112px 112px" },
                            gap: 1.5,
                            px: 2,
                            py: 1.25,
                            borderBottom: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                            bgcolor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.03 : 0.02),
                          })}
                        >
                          <Typography variant="caption" color="text.secondary">
                            {copy.text.columns.action}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {copy.text.columns.frequency}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {copy.text.columns.ev}
                          </Typography>
                          <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{ display: { xs: "none", md: "block" } }}
                          >
                            {copy.text.columns.size}
                          </Typography>
                        </Box>

                        {actions.map((action, index) => {
                          const isChosen =
                            action.name === result?.chosenAction ||
                            action.label === result?.chosenAction ||
                            action.isRecommended === true;
                          const progressValue = (() => {
                            if (action.frequency == null || Number.isNaN(action.frequency)) {
                              return 0;
                            }

                            return Math.max(0, Math.min(100, Math.abs(action.frequency) <= 1 ? action.frequency * 100 : action.frequency));
                          })();

                          return (
                            <Box
                              key={`${action.name}-${index}`}
                              sx={(theme) => ({
                                display: "grid",
                                gridTemplateColumns: {
                                  xs: "minmax(0, 1.5fr) 92px 84px",
                                  md: "minmax(0, 1.5fr) 132px 112px 112px",
                                },
                                gap: 1.5,
                                alignItems: "center",
                                px: 2,
                                py: 1.5,
                                borderBottom:
                                  index === actions.length - 1
                                    ? "none"
                                    : `1px solid ${alpha(theme.palette.text.primary, 0.06)}`,
                                bgcolor: isChosen
                                  ? alpha(theme.palette.primary.main, 0.08)
                                  : "transparent",
                              })}
                            >
                              <Stack spacing={0.85} minWidth={0}>
                                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                                  <Typography variant="body1" sx={{ fontWeight: 700 }}>
                                    {prettifyActionLabel(action)}
                                  </Typography>
                                  {isChosen ? (
                                    <Chip size="small" color="primary" label={copy.text.chosen} />
                                  ) : null}
                                  {action.isRecommended && !isChosen ? (
                                    <Chip
                                      size="small"
                                      variant="outlined"
                                      color="success"
                                      label={copy.text.recommended}
                                    />
                                  ) : null}
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
                                      ? "success.light"
                                      : (action.ev ?? 0) < 0
                                        ? "error.light"
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
                                {formatSize(action.size)}
                              </Typography>
                            </Box>
                          );
                        })}
                      </Box>
                    )}
                  </Stack>
                </>
              )}
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

export default SolveResultsPanel;
