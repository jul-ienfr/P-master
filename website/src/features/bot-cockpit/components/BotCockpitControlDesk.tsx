import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import { alpha, type SxProps, type Theme } from "@mui/material/styles";
import type { BotCockpitPayload } from "../../../lib/botCockpit";
import type { OperatorAlert, OperatorConsoleMode, OperatorMetric } from "./OperatorConsolePanel";

type BotDeskLocale = "en" | "fr";

export interface BotCockpitControlDeskProps {
  locale?: BotDeskLocale;
  payload: BotCockpitPayload;
  statusMessage: string;
  mode?: OperatorConsoleMode;
  alerts?: OperatorAlert[];
  metrics?: OperatorMetric[];
  loading?: boolean;
  refreshLabel?: string;
  refreshingLabel?: string;
  captureLabel?: string;
  shadowLabel?: string;
  manualOverrideLabel?: string;
  pauseLabel?: string;
  resumeLabel?: string;
  onRefresh?: () => void;
  onCaptureSpot?: () => void;
  onToggleShadowMode?: () => void;
  onToggleManualOverride?: () => void;
  onTogglePaused?: () => void;
  onSetAutomation?: (enabled: boolean) => void;
  sx?: SxProps<Theme>;
}

type DenseMetric = {
  label: string;
  value: string;
};

type DeskCopy = {
  title: string;
  subtitle: string;
  liveState: string;
  operatorState: string;
  latestDecision: string;
    latestDecisionHelp: string;
    status: string;
    statusFallback: string;
    gateDecision: string;
    incidents: string;
    controls: string;
  controlsHelp: string;
  automation: string;
  automationHelpOn: string;
  automationHelpOff: string;
  spotState: string;
  runtimeState: string;
  warnings: string;
  noAlerts: string;
  fallbackVisible: string;
  runtimeHealthy: string;
  runtimeDegraded: string;
  runtimeOffline: string;
  shadowOn: string;
  shadowOff: string;
  manualOn: string;
  manualOff: string;
  pausedOn: string;
  pausedOff: string;
  source: string;
  street: string;
  board: string;
  heroCards: string;
  villainRange: string;
  legalActions: string;
  history: string;
  position: string;
  players: string;
  pot: string;
  stack: string;
  latency: string;
  heroEv: string;
  exploitability: string;
  decisionSource: string;
  runtime: string;
  transport: string;
  uptime: string;
  llm: string;
  unknown: string;
  preflop: string;
  noRange: string;
  noHistory: string;
  noBoard: string;
  noCards: string;
  noLegal: string;
};

const COPY: Record<BotDeskLocale, DeskCopy> = {
  fr: {
    title: "État du bot",
    subtitle: "Les commandes utiles, l’action choisie, et la table actuelle.",
    liveState: "Bot",
    operatorState: "Mode",
    latestDecision: "Action choisie",
    latestDecisionHelp: "Ce que le bot veut faire tout de suite.",
    status: "Statut",
    statusFallback: "Aucun message de statut",
    gateDecision: "Sécurité",
    incidents: "Incidents",
    controls: "Commandes",
    controlsHelp: "Rafraîchir, capturer le spot, mettre en pause.",
    automation: "Automatisation",
    automationHelpOn: "Le bot suit le flux normal.",
    automationHelpOff: "Le bot reste sous contrôle manuel.",
    spotState: "Table actuelle",
    runtimeState: "État technique",
    warnings: "Alertes",
    noAlerts: "Rien à signaler",
    fallbackVisible: "Mode secours visible",
    runtimeHealthy: "Moteur local prêt",
    runtimeDegraded: "Moteur local dégradé",
    runtimeOffline: "Moteur local hors ligne",
    shadowOn: "Mode shadow actif",
    shadowOff: "Mode shadow inactif",
    manualOn: "Override manuel actif",
    manualOff: "Override manuel inactif",
    pausedOn: "Capture en pause",
    pausedOff: "Capture active",
    source: "Source",
    street: "Étape",
    board: "Tableau",
    heroCards: "Cartes héros",
    villainRange: "Range adverse",
    legalActions: "Actions possibles",
    history: "Dernières actions",
    position: "Position",
    players: "Joueurs",
    pot: "Pot",
    stack: "Tapis effectif",
    latency: "Latence",
    heroEv: "EV héros",
    exploitability: "Exploitabilité",
    decisionSource: "Origine de la décision",
    runtime: "Moteur",
    transport: "Transport",
    uptime: "Temps actif",
    llm: "Assistant",
    unknown: "inconnu",
    preflop: "Préflop",
    noRange: "non remontée",
    noHistory: "aucun noeud",
    noBoard: "aucun tableau",
    noCards: "cartes masquées",
    noLegal: "aucune",
  },
  en: {
    title: "Bot status",
    subtitle: "Useful controls, the chosen action, and the current table.",
    liveState: "Bot",
    operatorState: "Mode",
    latestDecision: "Chosen action",
    latestDecisionHelp: "What the bot wants to do right now.",
    status: "Status",
    statusFallback: "No status message",
    gateDecision: "Safety",
    incidents: "Incidents",
    controls: "Controls",
    controlsHelp: "Refresh, capture the spot, or pause the bot.",
    automation: "Automation",
    automationHelpOn: "The bot follows the normal flow.",
    automationHelpOff: "The bot stays under manual control.",
    spotState: "Current table",
    runtimeState: "Runtime",
    warnings: "Warnings",
    noAlerts: "Nothing to report",
    fallbackVisible: "Fallback visible",
    runtimeHealthy: "Local engine ready",
    runtimeDegraded: "Local engine degraded",
    runtimeOffline: "Local engine offline",
    shadowOn: "Shadow on",
    shadowOff: "Shadow off",
    manualOn: "Override on",
    manualOff: "Override off",
    pausedOn: "Capture paused",
    pausedOff: "Capture live",
    source: "Source",
    street: "Street",
    board: "Board",
    heroCards: "Hero cards",
    villainRange: "Villain range",
    legalActions: "Available actions",
    history: "Latest actions",
    position: "Position",
    players: "Players",
    pot: "Pot",
    stack: "Effective stack",
    latency: "Latency",
    heroEv: "Hero EV",
    exploitability: "Exploitability",
    decisionSource: "Decision source",
    runtime: "Engine",
    transport: "Transport",
    uptime: "Uptime",
    llm: "Assistant",
    unknown: "unknown",
    preflop: "Preflop",
    noRange: "not reported",
    noHistory: "no nodes",
    noBoard: "no board",
    noCards: "cards hidden",
    noLegal: "none",
  },
};

function formatBb(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)} bb`;
}

function formatMs(value: number) {
  return `${Math.round(value)} ms`;
}

function formatUptime(ms: number) {
  if (ms <= 0) {
    return "0s";
  }
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

function prettify(value: string | null | undefined, fallback: string) {
  if (!value) {
    return fallback;
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function listToLabel(values: string[], fallback: string, limit = 3) {
  if (!values.length) {
    return fallback;
  }
  if (values.length <= limit) {
    return values.join(" · ");
  }
  return `${values.slice(0, limit).join(" · ")} +${values.length - limit}`;
}

function extractVillainRangeSummary(payload: BotCockpitPayload, copy: DeskCopy) {
  const villains = Array.isArray(payload.spot.ranges.villains)
    ? payload.spot.ranges.villains.filter(
        (entry): entry is string => typeof entry === "string" && entry.trim().length > 0
      )
    : [];
  return listToLabel(villains, copy.noRange, 2);
}

function buildSpotMetrics(payload: BotCockpitPayload, copy: DeskCopy): DenseMetric[] {
  return [
    { label: copy.heroCards, value: listToLabel(payload.spot.heroCards, copy.noCards, 2) },
    { label: copy.board, value: listToLabel(payload.spot.board, copy.noBoard, 5) },
    {
      label: copy.street,
      value:
        payload.spot.board.length > 0
          ? prettify(payload.spot.street, copy.preflop)
          : copy.preflop,
    },
    { label: copy.position, value: payload.spot.heroPosition ?? copy.unknown },
    { label: copy.players, value: String(payload.spot.numPlayers) },
    { label: copy.legalActions, value: listToLabel(payload.spot.legalActions, copy.noLegal, 4) },
    {
      label: copy.history,
      value:
        payload.spot.actionHistory.length > 0
          ? listToLabel(payload.spot.actionHistory, copy.noHistory, 3)
          : copy.noHistory,
    },
    { label: copy.villainRange, value: extractVillainRangeSummary(payload, copy) },
  ];
}

function buildRuntimeMetrics(payload: BotCockpitPayload, copy: DeskCopy): DenseMetric[] {
  const gateReason =
    typeof payload.decision.metadata.gate_reason === "string" && payload.decision.metadata.gate_reason.length > 0
      ? payload.decision.metadata.gate_reason
      : payload.warnings.includes("fallback_used")
        ? "fallback_used"
        : "ready";
  const incidents = Array.isArray(payload.decision.metadata.incidents)
    ? payload.decision.metadata.incidents.filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0)
    : [];
  return [
    { label: copy.pot, value: `${payload.spot.pot.toFixed(1)} bb` },
    { label: copy.stack, value: `${payload.spot.effectiveStack.toFixed(1)} bb` },
    { label: copy.heroEv, value: formatBb(payload.decision.heroEv) },
    { label: copy.exploitability, value: formatBb(payload.decision.exploitability) },
    { label: copy.latency, value: formatMs(payload.decision.latencyMs) },
    { label: copy.decisionSource, value: prettify(payload.decision.source, copy.unknown) },
    { label: copy.runtime, value: payload.runtime.runtime || copy.unknown },
    { label: copy.transport, value: payload.transport.source || copy.unknown },
    { label: copy.uptime, value: formatUptime(payload.runtime.uptimeMs) },
    { label: copy.llm, value: payload.runtime.llm.enabled ? "on" : "off" },
    {
      label: copy.warnings,
      value: payload.warnings.length > 0 ? String(payload.warnings.length) : copy.noAlerts,
    },
    { label: copy.gateDecision, value: prettify(gateReason, copy.unknown) },
    { label: copy.incidents, value: incidents.length > 0 ? String(incidents.length) : copy.noAlerts },
    { label: copy.source, value: payload.spot.source || copy.unknown },
  ];
}

function sectionBorder(theme: Theme, opacity = 0.08) {
  return `1px solid ${alpha(theme.palette.text.primary, opacity)}`;
}

function mutedPanel(theme: Theme, opacity = 0.04) {
  return alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? opacity * 1.6 : opacity);
}

function getAlertColor(tone?: OperatorAlert["tone"]): "default" | "success" | "warning" | "error" | "primary" {
  if (tone === "success") {
    return "success";
  }
  if (tone === "warning") {
    return "warning";
  }
  if (tone === "error") {
    return "error";
  }
  return "primary";
}

function DetailSection({
  title,
  rows,
}: {
  title: string;
  rows: DenseMetric[];
}) {
  return (
    <Box
      sx={(theme) => ({
        border: sectionBorder(theme),
        borderRadius: 3,
        overflow: "hidden",
        backgroundColor: theme.palette.background.paper,
      })}
    >
      <Box
        sx={(theme) => ({
          px: 2,
          py: 1.25,
          borderBottom: sectionBorder(theme),
          backgroundColor: mutedPanel(theme, 0.03),
        })}
      >
        <Typography variant="overline" color="text.secondary" sx={{ letterSpacing: "0.12em" }}>
          {title}
        </Typography>
      </Box>
      <Stack divider={<Divider flexItem sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.08) })} />}>
        {rows.map((row) => (
          <Stack
            key={row.label}
            direction={{ xs: "column", sm: "row" }}
            justifyContent="space-between"
            spacing={0.75}
            sx={{ px: 2, py: 1.2 }}
          >
            <Typography variant="body2" color="text.secondary">
              {row.label}
            </Typography>
            <Typography variant="body2" sx={{ color: "text.primary", fontWeight: 600, textAlign: "right" }}>
              {row.value}
            </Typography>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}

function SummaryStat({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <Box
      sx={(theme) => ({
        border: sectionBorder(theme),
        borderRadius: 2.5,
        backgroundColor: mutedPanel(theme, 0.03),
        px: 1.5,
        py: 1.25,
      })}
    >
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body1" sx={{ color: "text.primary", fontWeight: 700, mt: 0.35 }}>
        {value}
      </Typography>
    </Box>
  );
}

function ModeChip({
  label,
  active,
}: {
  label: string;
  active: boolean;
}) {
  return (
    <Chip
      label={label}
      size="small"
      color={active ? "warning" : "default"}
      variant={active ? "filled" : "outlined"}
    />
  );
}

export function BotCockpitControlDesk({
  locale = "en",
  payload,
  statusMessage,
  mode = "live",
  alerts = [],
  metrics = [],
  loading = false,
  refreshLabel = "Refresh",
  refreshingLabel = "Refreshing...",
  captureLabel = "Capture",
  shadowLabel = "Shadow",
  manualOverrideLabel = "Override",
  pauseLabel = "Pause",
  resumeLabel = "Resume",
  onRefresh,
  onCaptureSpot,
  onToggleShadowMode,
  onToggleManualOverride,
  onTogglePaused,
  onSetAutomation,
  sx,
}: BotCockpitControlDeskProps) {
  const copy = COPY[locale];
  const automationActive =
    !payload.operator.paused &&
    !payload.operator.manualOverrideEnabled &&
    !payload.operator.shadowModeEnabled;
  const runtimeStateLabel =
    payload.warnings.length > 0
      ? copy.fallbackVisible
      : payload.state === "offline"
        ? copy.runtimeOffline
        : payload.state === "degraded"
          ? copy.runtimeDegraded
          : copy.runtimeHealthy;
  const spotMetrics = buildSpotMetrics(payload, copy);

  return (
    <Card
      variant="outlined"
      sx={[
        (theme) => ({
          borderRadius: 4,
          borderColor: alpha(theme.palette.text.primary, 0.1),
          backgroundColor: theme.palette.background.paper,
          boxShadow:
            theme.palette.mode === "dark"
              ? "0 18px 44px rgba(0, 0, 0, 0.28)"
              : "0 10px 30px rgba(15, 23, 42, 0.06)",
          color: theme.palette.text.primary,
        }),
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
    >
      {loading ? <LinearProgress /> : null}
      <CardContent sx={{ p: { xs: 2, md: 2.5 } }}>
        <Stack spacing={2}>
          <Stack
            direction={{ xs: "column", xl: "row" }}
            spacing={1.5}
            justifyContent="space-between"
            alignItems={{ xs: "flex-start", xl: "center" }}
          >
            <Box>
              <Typography variant="overline" color="text.secondary" sx={{ letterSpacing: "0.14em" }}>
                Bot Cockpit
              </Typography>
              <Typography variant="h5" sx={{ color: "text.primary" }}>
                {copy.title}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: "68ch" }}>
                {copy.subtitle}
              </Typography>
            </Box>

            <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
              <Chip
                label={`${copy.liveState} · ${prettify(payload.state, copy.unknown)}`}
                color={payload.state === "live" ? "success" : payload.state === "degraded" ? "warning" : "default"}
                variant="outlined"
              />
              <Chip label={`${copy.operatorState} · ${prettify(mode, copy.unknown)}`} variant="outlined" />
              <Chip label={`${copy.runtime} · ${payload.runtime.runtime || copy.unknown}`} variant="outlined" />
            </Stack>
          </Stack>

          <Box
            sx={(theme) => ({
              border: sectionBorder(theme),
              borderRadius: 3,
              backgroundColor: mutedPanel(theme, 0.03),
              p: 2,
            })}
          >
            <Stack spacing={1.25}>
              <Stack
                direction={{ xs: "column", lg: "row" }}
                justifyContent="space-between"
                spacing={1}
                alignItems={{ xs: "flex-start", lg: "center" }}
                >
                  <Box>
                  <Typography variant="overline" color="text.secondary" sx={{ letterSpacing: "0.12em" }}>
                    {copy.latestDecision}
                  </Typography>
                  <Typography variant="h4" sx={{ color: "text.primary", mt: 0.3 }}>
                    {prettify(payload.decision.chosenAction, copy.unknown)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.4 }}>
                    {copy.latestDecisionHelp}
                  </Typography>
                </Box>
                <Chip
                  label={runtimeStateLabel}
                  color={
                    payload.state === "live" && payload.warnings.length === 0
                      ? "success"
                      : payload.state === "offline"
                        ? "default"
                        : "warning"
                  }
                  variant="outlined"
                />
              </Stack>

              <Box
                sx={{
                  display: "grid",
                  gap: 1,
                  gridTemplateColumns: {
                    xs: "repeat(2, minmax(0, 1fr))",
                    lg: "repeat(4, minmax(0, 1fr))",
                  },
                }}
              >
                <SummaryStat label={copy.heroEv} value={formatBb(payload.decision.heroEv)} />
                <SummaryStat label={copy.latency} value={formatMs(payload.decision.latencyMs)} />
                <SummaryStat label={copy.decisionSource} value={prettify(payload.decision.source, copy.unknown)} />
                <SummaryStat label={copy.exploitability} value={formatBb(payload.decision.exploitability)} />
              </Box>

              <Box
                sx={(theme) => ({
                  border: sectionBorder(theme),
                  borderRadius: 2.5,
                  backgroundColor: theme.palette.background.paper,
                  px: 1.5,
                  py: 1.15,
                })}
              >
                <Typography variant="caption" color="text.secondary">
                  {copy.status}
                </Typography>
                <Typography variant="body2" sx={{ color: "text.primary", mt: 0.35 }}>
                  {statusMessage || copy.statusFallback}
                </Typography>
              </Box>
            </Stack>
          </Box>

          <Box
            sx={(theme) => ({
              border: sectionBorder(theme),
              borderRadius: 3,
              p: 2,
            })}
          >
            <Stack spacing={1.25}>
              <Stack
                direction={{ xs: "column", lg: "row" }}
                justifyContent="space-between"
                spacing={1}
                alignItems={{ xs: "flex-start", lg: "center" }}
              >
                <Box>
                  <Typography variant="overline" color="text.secondary" sx={{ letterSpacing: "0.12em" }}>
                    {copy.controls}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.35 }}>
                    {copy.controlsHelp}
                  </Typography>
                </Box>
                <ModeChip label={payload.operator.paused ? copy.pausedOn : copy.pausedOff} active={payload.operator.paused} />
              </Stack>

              <Stack direction={{ xs: "column", md: "row" }} spacing={1} useFlexGap flexWrap="wrap">
                <Button variant="contained" onClick={onRefresh} disabled={!onRefresh || loading}>
                  {loading ? refreshingLabel : refreshLabel}
                </Button>
                <Button variant="outlined" onClick={onCaptureSpot} disabled={!onCaptureSpot || loading}>
                  {captureLabel}
                </Button>
                <Button
                  variant={payload.operator.shadowModeEnabled ? "contained" : "outlined"}
                  color={payload.operator.shadowModeEnabled ? "primary" : "inherit"}
                  onClick={onToggleShadowMode}
                  disabled={!onToggleShadowMode || loading}
                >
                  {shadowLabel}
                </Button>
                <Button
                  variant={payload.operator.manualOverrideEnabled ? "contained" : "outlined"}
                  color={payload.operator.manualOverrideEnabled ? "secondary" : "inherit"}
                  onClick={onToggleManualOverride}
                  disabled={!onToggleManualOverride || loading}
                >
                  {manualOverrideLabel}
                </Button>
                <Button variant="outlined" onClick={onTogglePaused} disabled={!onTogglePaused || loading}>
                  {payload.operator.paused ? resumeLabel : pauseLabel}
                </Button>
              </Stack>

              <Box
                sx={(theme) => ({
                  border: sectionBorder(theme),
                  borderRadius: 2.5,
                  backgroundColor: mutedPanel(theme, 0.03),
                  px: 1.5,
                  py: 1.2,
                })}
              >
                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  justifyContent="space-between"
                  spacing={1}
                  alignItems={{ xs: "flex-start", sm: "center" }}
                >
                  <Box>
                    <Typography variant="body2" sx={{ color: "text.primary", fontWeight: 600 }}>
                      {copy.automation}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {automationActive ? copy.automationHelpOn : copy.automationHelpOff}
                    </Typography>
                  </Box>
                  <Switch checked={automationActive} disabled={loading} onChange={(_, checked) => onSetAutomation?.(checked)} />
                </Stack>
              </Box>
            </Stack>
          </Box>

          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
            {alerts.length > 0 ? (
              alerts.map((alert, index) => (
                <Chip
                  key={alert.id ?? `${alert.label}-${index}`}
                  label={alert.label}
                  color={getAlertColor(alert.tone)}
                  variant="outlined"
                  size="small"
                />
              ))
            ) : (
              <Chip label={copy.noAlerts} color="success" variant="outlined" size="small" />
            )}
            {metrics.slice(0, 4).map((metric) => (
              <Chip
                key={`${metric.label}-${metric.value}`}
                label={`${metric.label} · ${metric.value}`}
                variant="outlined"
                size="small"
              />
            ))}
          </Stack>

          <Box
            sx={{
              display: "grid",
              gap: 1.5,
              gridTemplateColumns: { xs: "1fr" },
            }}
          >
            <DetailSection title={copy.spotState} rows={spotMetrics} />
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

export default BotCockpitControlDesk;
