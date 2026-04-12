import type { ReactElement } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { alpha } from "@mui/material/styles";
import AnalyticsRoundedIcon from "@mui/icons-material/AnalyticsRounded";
import TrendingDownRoundedIcon from "@mui/icons-material/TrendingDownRounded";
import TrendingUpRoundedIcon from "@mui/icons-material/TrendingUpRounded";
import AutoGraphRoundedIcon from "@mui/icons-material/AutoGraphRounded";
import BookmarkRoundedIcon from "@mui/icons-material/BookmarkRounded";
import BoltRoundedIcon from "@mui/icons-material/BoltRounded";
import CachedRoundedIcon from "@mui/icons-material/CachedRounded";
import EventRoundedIcon from "@mui/icons-material/EventRounded";
import FolderSpecialRoundedIcon from "@mui/icons-material/FolderSpecialRounded";
import InsightsRoundedIcon from "@mui/icons-material/InsightsRounded";
import PlayCircleOutlineRoundedIcon from "@mui/icons-material/PlayCircleOutlineRounded";
import ReportProblemRoundedIcon from "@mui/icons-material/ReportProblemRounded";
import ScheduleRoundedIcon from "@mui/icons-material/ScheduleRounded";
import TrendingFlatRoundedIcon from "@mui/icons-material/TrendingFlatRounded";
import { getSessionOverviewCopy } from "../../../lib/workstationI18n";

import type {
  ReplayAnalyticsState,
  ReplaySignalTone,
  SessionKpi,
  SessionLeakGroup,
  SessionOverviewPanelProps,
} from "./types";

type StateTone = {
  label: string;
  color: "default" | "primary" | "secondary" | "success" | "warning" | "error";
  icon: ReactElement;
  description: string;
};

const DEFAULT_TITLE = "Replay analytics";
const DEFAULT_SUBTITLE =
  "Track session health, trend KPIs, and the leak clusters that are worth the next review pass.";
const DEFAULT_EMPTY_MESSAGE =
  "No replay session is attached yet. Connect a session snapshot to unlock summary KPIs, leak tags, and review guidance.";

function getStateTone(state: ReplayAnalyticsState, locale: "en" | "fr"): StateTone {
  switch (state) {
    case "loading":
      return {
        label: locale === "fr" ? "Chargement" : "Loading",
        color: "secondary",
        icon: <PlayCircleOutlineRoundedIcon fontSize="small" />,
        description:
          locale === "fr"
            ? "La session replay se prépare et les cartes d’analyse se mettent à jour."
            : "The replay session is being assembled and the analytics cards are warming up.",
      };
    case "ready":
      return {
        label: locale === "fr" ? "Prête" : "Ready",
        color: "success",
        icon: <BoltRoundedIcon fontSize="small" />,
        description:
          locale === "fr"
            ? "Les résumés de session et les signaux de tendance sont prêts pour la revue."
            : "Session summaries and trend signals are ready for review.",
      };
    case "degraded":
      return {
        label: locale === "fr" ? "Dégradée" : "Degraded",
        color: "warning",
        icon: <ReportProblemRoundedIcon fontSize="small" />,
        description:
          locale === "fr"
            ? "Il manque une partie des données replay, mais le panneau reste utilisable."
            : "Some replay data is missing, but the panel remains usable.",
      };
    case "offline":
      return {
        label: locale === "fr" ? "Hors ligne" : "Offline",
        color: "primary",
        icon: <CachedRoundedIcon fontSize="small" />,
        description:
          locale === "fr"
            ? "Le panneau fonctionne en mode local sûr avec des données replay en cache."
            : "The panel is in offline-safe mode and showing cached replay data.",
      };
    case "error":
      return {
        label: locale === "fr" ? "Erreur" : "Error",
        color: "error",
        icon: <ReportProblemRoundedIcon fontSize="small" />,
        description:
          locale === "fr"
            ? "Le dernier chargement replay ne s’est pas terminé correctement."
            : "The latest replay fetch did not complete cleanly.",
      };
    case "idle":
    default:
      return {
        label: locale === "fr" ? "En attente" : "Idle",
        color: "default",
        icon: <InsightsRoundedIcon fontSize="small" />,
        description:
          locale === "fr" ? "En attente d’une session replay." : "Waiting for a replay session.",
      };
  }
}

function toneToColor(tone?: ReplaySignalTone): "default" | "primary" | "secondary" | "success" | "warning" | "error" {
  switch (tone) {
    case "success":
      return "success";
    case "warning":
      return "warning";
    case "error":
      return "error";
    case "info":
      return "primary";
    case "neutral":
    default:
      return "default";
  }
}

function formatCount(value?: number) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `${value}`;
}

function renderTrendIcon(delta?: string) {
  if (!delta) {
    return <TrendingFlatRoundedIcon fontSize="small" />;
  }

  if (delta.trim().startsWith("-")) {
    return <TrendingDownRoundedIcon fontSize="small" />;
  }

  if (delta.trim().startsWith("+")) {
    return <TrendingUpRoundedIcon fontSize="small" />;
  }

  return <TrendingFlatRoundedIcon fontSize="small" />;
}

function StatCard({
  item,
}: {
  item: SessionKpi;
}) {
  return (
    <Box
      sx={(theme) => ({
        flex: "1 1 180px",
        minWidth: 0,
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
          {item.icon ?? <AnalyticsRoundedIcon fontSize="small" />}
        </Box>
        <Stack spacing={0.35} minWidth={0}>
          <Typography variant="caption" color="text.secondary">
            {item.label}
          </Typography>
          <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
            <Typography variant="h6">{item.value}</Typography>
            {item.delta ? (
              <Chip
                icon={renderTrendIcon(item.delta)}
                label={item.delta}
                size="small"
                color={item.tone ? toneToColor(item.tone) : "default"}
                variant={item.tone && item.tone !== "neutral" ? "filled" : "outlined"}
              />
            ) : null}
          </Stack>
          {item.helper ? (
            <Typography variant="body2" color="text.secondary">
              {item.helper}
            </Typography>
          ) : null}
        </Stack>
      </Stack>
    </Box>
  );
}

function LeakGroupCard({ group }: { group: SessionLeakGroup }) {
  return (
    <Box
      sx={(theme) => ({
        flex: "1 1 240px",
        minWidth: 0,
        borderRadius: 4,
        border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
        background:
          theme.palette.mode === "dark"
            ? "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015))"
            : "linear-gradient(180deg, rgba(16,24,40,0.03), rgba(16,24,40,0.012))",
        px: 2.25,
        py: 2,
      })}
    >
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1} alignItems="flex-start" justifyContent="space-between">
          <Box>
            <Typography variant="subtitle1" sx={{ lineHeight: 1.2 }}>
              {group.label}
            </Typography>
            {group.detail ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.35 }}>
                {group.detail}
              </Typography>
            ) : null}
          </Box>
          <Chip
            label={formatCount(group.count)}
            color={toneToColor(group.tone)}
            variant={group.tone && group.tone !== "neutral" ? "filled" : "outlined"}
            size="small"
          />
        </Stack>

        {group.tags && group.tags.length > 0 ? (
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            {group.tags.map((tag) => (
              <Chip
                key={`${group.id ?? group.label}-${tag}`}
                label={tag}
                size="small"
                variant="outlined"
                sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
              />
            ))}
          </Stack>
        ) : null}
      </Stack>
    </Box>
  );
}

export function SessionOverviewPanel({
  title = DEFAULT_TITLE,
  subtitle = DEFAULT_SUBTITLE,
  locale = "en",
  state = "idle",
  sessionName,
  sessionMeta,
  summary,
  sessionStats = [],
  trendKpis = [],
  leakGroups = [],
  headlineTags = [],
  emptyMessage = DEFAULT_EMPTY_MESSAGE,
  onReviewLatest,
  onOpenTimeline,
  onExport,
  sx,
}: SessionOverviewPanelProps) {
  const copy = getSessionOverviewCopy(locale);
  const tone = getStateTone(state, locale);
  const isEmpty = state === "idle" && sessionStats.length === 0 && trendKpis.length === 0 && leakGroups.length === 0;

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
                {title}
              </Typography>
              <Typography variant="h5" sx={{ mt: 0.25 }}>
                {sessionName || copy.sessionFallback}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 780, mt: 0.5 }}>
                {subtitle}
              </Typography>
            </Box>

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip icon={tone.icon} label={tone.label} color={tone.color} variant={tone.color === "default" ? "outlined" : "filled"} />
              {sessionMeta ? <Chip label={sessionMeta} variant="outlined" sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} /> : null}
              {headlineTags.map((tag) => (
                <Chip key={tag} label={tag} variant="outlined" sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} />
              ))}
            </Stack>
          </Stack>

          {summary ? <Alert severity={state === "error" ? "error" : state === "degraded" ? "warning" : "info"} variant="outlined">{summary}</Alert> : null}

          {state === "loading" ? (
            <LinearProgress color="secondary" />
          ) : null}

          {isEmpty ? (
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
                  icon={<BookmarkRoundedIcon fontSize="small" />}
                  label={copy.waiting}
                  variant="outlined"
                  sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                />
                <Typography variant="body1">{emptyMessage}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {copy.waitingHelp}
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
                    <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap>
                      <Chip label={copy.summaryChip} color="success" size="small" />
                      <Chip label={tone.label} variant="outlined" sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} />
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      {copy.sessionFocus}
                    </Typography>
                    <Typography variant="h4" sx={{ letterSpacing: "-0.04em" }}>
                      {sessionName || copy.dashboardFallback}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {sessionMeta || copy.dashboardHelp}
                    </Typography>
                  </Stack>
                </Box>

                {(sessionStats[0] ? sessionStats : []).map((item) => (
                  <StatCard key={item.label} item={item} />
                ))}
              </Stack>

              {trendKpis.length > 0 ? (
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <AutoGraphRoundedIcon color="primary" fontSize="small" />
                    <Typography variant="h6">{copy.trendTitle}</Typography>
                  </Stack>
                  <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                    {trendKpis.map((item) => (
                      <StatCard key={item.label} item={item} />
                    ))}
                  </Stack>
                </Stack>
              ) : null}

              <Divider />

              <Stack spacing={1.5}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <FolderSpecialRoundedIcon color="primary" fontSize="small" />
                  <Typography variant="h6">{copy.leakTitle}</Typography>
                </Stack>
                {leakGroups.length > 0 ? (
                  <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} useFlexGap flexWrap="wrap">
                    {leakGroups.map((group) => (
                      <LeakGroupCard key={group.id ?? group.label} group={group} />
                    ))}
                  </Stack>
                ) : (
                  <Alert severity="info" variant="outlined">
                    {copy.noLeaks}
                  </Alert>
                )}
              </Stack>

              <Divider />

              <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} justifyContent="space-between" alignItems={{ xs: "stretch", md: "center" }}>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip icon={<EventRoundedIcon fontSize="small" />} label={copy.reviewable} variant="outlined" sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} />
                  <Chip icon={<ScheduleRoundedIcon fontSize="small" />} label={copy.timelineReady} variant="outlined" sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} />
                </Stack>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap justifyContent={{ xs: "stretch", md: "flex-end" }}>
                  <Tooltip title={tone.description}>
                    <Button variant="outlined" startIcon={<InsightsRoundedIcon />} onClick={onOpenTimeline} disabled={!onOpenTimeline}>
                      {copy.openTimeline}
                    </Button>
                  </Tooltip>
                  <Button variant="contained" startIcon={<PlayCircleOutlineRoundedIcon />} onClick={onReviewLatest} disabled={!onReviewLatest}>
                    {copy.reviewLatest}
                  </Button>
                  <Button variant="text" onClick={onExport} disabled={!onExport}>
                    {copy.export}
                  </Button>
                </Stack>
              </Stack>
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

export default SessionOverviewPanel;
