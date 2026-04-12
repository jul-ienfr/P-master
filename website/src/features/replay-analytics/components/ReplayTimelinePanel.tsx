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
  Typography,
} from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { alpha } from "@mui/material/styles";
import HistoryRoundedIcon from "@mui/icons-material/HistoryRounded";
import KeyboardArrowRightRoundedIcon from "@mui/icons-material/KeyboardArrowRightRounded";
import PlayCircleOutlineRoundedIcon from "@mui/icons-material/PlayCircleOutlineRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import TimelineRoundedIcon from "@mui/icons-material/TimelineRounded";
import VisibilityRoundedIcon from "@mui/icons-material/VisibilityRounded";
import WarningAmberRoundedIcon from "@mui/icons-material/WarningAmberRounded";

import type { ReplayAnalyticsState, ReplayTimelinePanelProps, ReplayTimelineSpot } from "./types";
import type { ReactElement } from "react";
import { getReplayTimelineCopy } from "../../../lib/workstationI18n";

type StateTone = {
  label: string;
  color: "default" | "primary" | "secondary" | "success" | "warning" | "error";
  icon: ReactElement;
  description: string;
};

const DEFAULT_TITLE = "Replay timeline";
const DEFAULT_SUBTITLE =
  "Walk through the session in order, inspect the replayed spots, and jump directly to the nodes worth a deeper review.";
const DEFAULT_EMPTY_MESSAGE =
  "No replay spots are attached yet. Connect a session or hydrate the timeline to inspect each reviewed node.";
const DEFAULT_LOADING_MESSAGE =
  "Hydrating the replay timeline and preparing the review queue.";

function getStateTone(state: ReplayAnalyticsState, locale: "en" | "fr"): StateTone {
  switch (state) {
    case "loading":
      return {
        label: locale === "fr" ? "Chargement" : "Loading",
        color: "secondary",
        icon: <PlayCircleOutlineRoundedIcon fontSize="small" />,
        description:
          locale === "fr"
            ? "La chronologie de relecture est en cours de préparation."
            : "The replay timeline is being assembled.",
      };
    case "ready":
      return {
        label: locale === "fr" ? "Prête" : "Ready",
        color: "success",
        icon: <TimelineRoundedIcon fontSize="small" />,
        description:
          locale === "fr" ? "La chronologie est prête pour la revue." : "The timeline is ready for review.",
      };
    case "degraded":
      return {
        label: locale === "fr" ? "Dégradée" : "Degraded",
        color: "warning",
        icon: <WarningAmberRoundedIcon fontSize="small" />,
        description:
          locale === "fr"
            ? "Certains éléments replay manquent, mais la revue reste utilisable."
            : "Some replay items are missing, but the review flow remains usable.",
      };
    case "offline":
      return {
        label: locale === "fr" ? "Hors ligne" : "Offline",
        color: "primary",
        icon: <RefreshRoundedIcon fontSize="small" />,
        description:
          locale === "fr"
            ? "Les données replay affichées restent locales et sûres."
            : "Offline-safe replay data is being shown.",
      };
    case "error":
      return {
        label: locale === "fr" ? "Erreur" : "Error",
        color: "error",
        icon: <WarningAmberRoundedIcon fontSize="small" />,
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
        icon: <HistoryRoundedIcon fontSize="small" />,
        description:
          locale === "fr" ? "En attente d’une session replay." : "Waiting for a replay session.",
      };
  }
}

function formatTimestamp(value?: string) {
  if (!value) {
    return "";
  }
  return value;
}

type ReplayTimelineCopy = {
  reviewTitle: string;
  spots: (count: number) => string;
  sortByImpact: string;
  sortTimeline: string;
  impactFallback: string;
  waiting: string;
  waitingHelp: string;
  queue: string;
  history: string;
  refresh: string;
  latest: string;
  openSpot: string;
  openSpotHint: string;
  reviewed: string;
  selected: string;
  streetFallback: string;
  timestampFallback: string;
  heroEv: string;
  exploitability: string;
  confidence: string;
  canonicalSpot: string;
  gateResult: string;
  runtimeMetrics: string;
  incidents: string;
  decisionTrace: string;
  selectedDetailTitle: string;
  selectedDetailSubtitle: string;
  selectedDetailEmpty: string;
  spotBlock: string;
  gateBlock: string;
  traceBlock: string;
  rlDiff: string;
  rlAggregateTitle: string;
  rlAggregateSubtitle: string;
  rlSpotsWithDiff: string;
  rlAverageDelta: string;
  rlImpactedStreets: string;
  rlShiftSignals: string;
  rlNoAggregate: string;
};

type RlAggregateSummary = {
  diffCount: number;
  averageDeltaEv: number | null;
  impactedStreets: string[];
  shiftSignals: string[];
};

function parseSignedBb(value?: string): number | null {
  if (!value) {
    return null;
  }

  const match = value.match(/[-+]?\d+(?:[.,]\d+)?/);
  if (!match) {
    return null;
  }

  const normalized = Number(match[0].replace(",", "."));
  return Number.isFinite(normalized) ? normalized : null;
}

function formatSignedBb(value: number) {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toFixed(2)} bb`;
}

function formatImpactScore(value?: number): string | null {
  if (!Number.isFinite(value)) {
    return null;
  }
  return Math.abs(value as number) >= 10 ? `${Math.round(value as number)}` : (value as number).toFixed(1);
}

function buildRlAggregateSummary(items: ReplayTimelineSpot[]): RlAggregateSummary | null {
  const diffItems = items.filter(
    (item) => item.rlDiffSummary?.deltaEv || item.rlDiffSummary?.actionShift || item.rlDiffSummary?.confidenceShift
  );
  if (diffItems.length === 0) {
    return null;
  }

  const deltaValues = diffItems
    .map((item) => parseSignedBb(item.rlDiffSummary?.deltaEv))
    .filter((value): value is number => value !== null);
  const averageDeltaEv =
    deltaValues.length > 0 ? deltaValues.reduce((sum, value) => sum + value, 0) / deltaValues.length : null;

  const impactedStreets = Array.from(
    new Set(
      diffItems
        .map((item) => item.street?.trim())
        .filter((street): street is string => Boolean(street))
    )
  ).slice(0, 4);

  const shiftSignals = [
    diffItems.some((item) => Boolean(item.rlDiffSummary?.actionShift)) ? "action mix" : null,
    diffItems.some((item) => Boolean(item.rlDiffSummary?.confidenceShift)) ? "confidence" : null,
    deltaValues.length > 0 ? "hero EV" : null,
  ].filter((value): value is string => value !== null);

  return {
    diffCount: diffItems.length,
    averageDeltaEv,
    impactedStreets,
    shiftSignals,
  };
}

function RlAggregateCard({
  summary,
  copy,
  locale,
}: {
  summary: RlAggregateSummary | null;
  copy: ReplayTimelineCopy;
  locale: "en" | "fr";
}) {
  const shiftSignalsLabel =
    summary && summary.shiftSignals.length > 0
      ? locale === "fr"
        ? summary.shiftSignals
            .map((signal) => {
              if (signal === "action mix") {
                return "action";
              }
              if (signal === "confidence") {
                return "confiance";
              }
              return "EV hero";
            })
            .join(" · ")
        : summary.shiftSignals.join(" · ")
      : copy.rlNoAggregate;

  return (
    <Stack
      spacing={1.25}
      sx={(theme) => ({
        p: 1.75,
        borderRadius: 4,
        border: `1px solid ${alpha(theme.palette.secondary.main, 0.18)}`,
        background: `linear-gradient(180deg, ${alpha(theme.palette.secondary.main, 0.12)}, ${alpha(
          theme.palette.secondary.main,
          0.04
        )})`,
      })}
    >
      <Box>
        <Typography variant="overline" color="text.secondary">
          {copy.rlAggregateTitle}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
          {copy.rlAggregateSubtitle}
        </Typography>
      </Box>

      {summary ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" color="secondary" label={`${copy.rlSpotsWithDiff} ${summary.diffCount}`} />
          {summary.averageDeltaEv !== null ? (
            <Chip
              size="small"
              variant="outlined"
              label={`${copy.rlAverageDelta} ${formatSignedBb(summary.averageDeltaEv)}`}
            />
          ) : null}
          <Chip
            size="small"
            variant="outlined"
            label={`${copy.rlImpactedStreets} ${summary.impactedStreets.length > 0 ? summary.impactedStreets.join(" · ") : copy.rlNoAggregate}`}
          />
          <Chip size="small" variant="outlined" label={`${copy.rlShiftSignals} ${shiftSignalsLabel}`} />
        </Stack>
      ) : (
        <Typography variant="body2" color="text.secondary">
          {copy.rlNoAggregate}
        </Typography>
      )}
    </Stack>
  );
}

function DetailBlock({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: string }>;
}) {
  if (rows.length === 0) {
    return null;
  }

  return (
    <Stack
      spacing={1}
      sx={(theme) => ({
        p: 1.5,
        borderRadius: 3,
        border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
        bgcolor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.03 : 0.02),
      })}
    >
      <Typography variant="subtitle2">{title}</Typography>
      {rows.map((row) => (
        <Stack
          key={`${title}-${row.label}-${row.value}`}
          direction="row"
          spacing={1}
          justifyContent="space-between"
          alignItems="flex-start"
        >
          <Typography variant="caption" color="text.secondary" sx={{ minWidth: 0, flexShrink: 0 }}>
            {row.label}
          </Typography>
          <Typography variant="body2" sx={{ textAlign: "right", minWidth: 0 }}>
            {row.value}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}

function TimelineSpotCard({
  item,
  selected,
  onSelect,
  copy,
}: {
  item: ReplayTimelineSpot;
  selected: boolean;
  onSelect?: (spotId: string) => void;
  copy: ReplayTimelineCopy;
}) {
  return (
    <Box
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={onSelect ? () => onSelect(item.id) : undefined}
      onKeyDown={
        onSelect
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect(item.id);
              }
            }
          : undefined
      }
      sx={(theme) => ({
        display: "grid",
        gridTemplateColumns: "22px minmax(0, 1fr)",
        gap: 1.5,
        alignItems: "stretch",
        cursor: onSelect ? "pointer" : "default",
        outline: "none",
        "&:hover .replay-timeline-card": onSelect
          ? {
              borderColor: alpha(theme.palette.primary.main, 0.4),
              transform: "translateY(-1px)",
            }
          : undefined,
      })}
    >
      <Box sx={{ position: "relative", display: "flex", justifyContent: "center" }}>
        <Box
          sx={(theme) => ({
            width: 12,
            height: 12,
            borderRadius: "50%",
            mt: 2,
            bgcolor: selected ? theme.palette.primary.main : theme.palette.text.primary,
            boxShadow: selected ? `0 0 0 6px ${alpha(theme.palette.primary.main, 0.14)}` : "none",
          })}
        />
        <Box
          sx={(theme) => ({
            position: "absolute",
            top: 0,
            bottom: -20,
            width: 2,
            borderRadius: 99,
            bgcolor: alpha(theme.palette.text.primary, 0.08),
          })}
        />
      </Box>

      <Card
        className="replay-timeline-card"
        variant="outlined"
        sx={(theme) => ({
          borderRadius: 4,
          borderColor: selected ? alpha(theme.palette.primary.main, 0.42) : alpha(theme.palette.text.primary, 0.08),
          background: selected
            ? `linear-gradient(180deg, ${alpha(theme.palette.primary.main, 0.14)}, ${alpha(
                theme.palette.text.primary,
                theme.palette.mode === "dark" ? 0.03 : 0.015
              )})`
            : theme.palette.mode === "dark"
              ? "linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02))"
              : "linear-gradient(180deg, rgba(16,24,40,0.03), rgba(16,24,40,0.015))",
          transition: "transform 180ms ease, border-color 180ms ease, background 180ms ease",
        })}
      >
        <CardContent sx={{ p: 2.25, "&:last-child": { pb: 2.25 } }}>
          <Stack spacing={1.25}>
            <Stack direction="row" spacing={1} justifyContent="space-between" alignItems="flex-start">
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="subtitle1" sx={{ lineHeight: 1.2 }}>
                  {item.title}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.35 }}>
                  {formatTimestamp(item.timestamp) || copy.timestampFallback}
                </Typography>
              </Box>
              <Chip
                label={item.street ?? copy.streetFallback}
                size="small"
                variant="outlined"
                sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
              />
            </Stack>

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {item.action ? <Chip label={item.action} color="primary" size="small" /> : null}
              {item.result ? <Chip label={item.result} color="success" size="small" variant="outlined" /> : null}
              {item.reviewed ? (
                <Chip label={copy.reviewed} color="success" size="small" variant="outlined" />
              ) : null}
              {selected ? <Chip label={copy.selected} color="secondary" size="small" /> : null}
            </Stack>

            <Stack direction="row" spacing={1.25} flexWrap="wrap" useFlexGap>
              {item.heroEv ? (
                <Chip label={`${copy.heroEv} ${item.heroEv}`} size="small" variant="outlined" sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} />
              ) : null}
              {item.impactScore !== undefined ? (
                <Chip
                  label={`${item.impactLabel ?? (copy.sortByImpact.includes("impact") ? "Impact" : "Impact")} ${formatImpactScore(item.impactScore)}`}
                  size="small"
                  color="warning"
                  variant="outlined"
                  sx={(theme) => ({ borderColor: alpha(theme.palette.warning.main, 0.3) })}
                />
              ) : null}
              {item.exploitability ? (
                <Chip label={`${copy.exploitability} ${item.exploitability}`} size="small" variant="outlined" sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} />
              ) : null}
              {item.confidence ? (
                <Chip label={`${copy.confidence} ${item.confidence}`} size="small" variant="outlined" sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} />
              ) : null}
              {item.rlDiffSummary?.deltaEv ? (
                <Chip
                  label={`${copy.rlDiff} ${item.rlDiffSummary.deltaEv}`}
                  size="small"
                  color="secondary"
                  variant="outlined"
                  sx={(theme) => ({ borderColor: alpha(theme.palette.secondary.main, 0.24) })}
                />
              ) : null}
            </Stack>

            {item.rlDiffSummary?.actionShift || item.rlDiffSummary?.confidenceShift ? (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {item.rlDiffSummary.actionShift ? (
                  <Chip
                    label={item.rlDiffSummary.actionShift}
                    size="small"
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.secondary.main, 0.24) })}
                  />
                ) : null}
                {item.rlDiffSummary.confidenceShift ? (
                  <Chip
                    label={item.rlDiffSummary.confidenceShift}
                    size="small"
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.secondary.main, 0.24) })}
                  />
                ) : null}
              </Stack>
            ) : null}

            {item.canonicalSpot || item.gateResult || (item.runtimeMetrics && item.runtimeMetrics.length > 0) ? (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {item.canonicalSpot ? (
                  <Chip
                    label={`${copy.canonicalSpot} ${item.canonicalSpot}`}
                    size="small"
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                  />
                ) : null}
                {item.gateResult ? (
                  <Chip
                    label={`${copy.gateResult} ${item.gateResult}`}
                    size="small"
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                  />
                ) : null}
                {item.runtimeMetrics?.map((metric) => (
                  <Chip
                    key={`${item.id}-runtime-${metric}`}
                    label={`${copy.runtimeMetrics} ${metric}`}
                    size="small"
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                  />
                ))}
              </Stack>
            ) : null}

            {item.tags && item.tags.length > 0 ? (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {item.tags.map((tag) => (
                  <Chip
                    key={`${item.id}-${tag}`}
                    label={tag}
                    size="small"
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                  />
                ))}
              </Stack>
            ) : null}

            {item.note ? (
              <Typography variant="body2" color="text.secondary">
                {item.note}
              </Typography>
            ) : null}

            {item.incidents && item.incidents.length > 0 ? (
              <Typography variant="body2" color="text.secondary">
                <strong>{copy.incidents}:</strong> {item.incidents.join(" · ")}
              </Typography>
            ) : null}

            {item.decisionTrace && item.decisionTrace.length > 0 ? (
              <Typography variant="body2" color="text.secondary">
                <strong>{copy.decisionTrace}:</strong> {item.decisionTrace.join(" -> ")}
              </Typography>
            ) : null}

            {onSelect ? (
              <Stack direction="row" spacing={1} alignItems="center">
                <Button size="small" variant={selected ? "contained" : "outlined"} endIcon={<KeyboardArrowRightRoundedIcon />}>
                  {copy.openSpot}
                </Button>
                <Typography variant="caption" color="text.secondary">
                  {copy.openSpotHint}
                </Typography>
              </Stack>
            ) : null}
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}

export function ReplayTimelinePanel({
  title = DEFAULT_TITLE,
  subtitle = DEFAULT_SUBTITLE,
  locale = "en",
  state = "idle",
  items = [],
  selectedSpotId,
  emptyMessage = DEFAULT_EMPTY_MESSAGE,
  loadingMessage = DEFAULT_LOADING_MESSAGE,
  sortedByImpact = false,
  impactSummary,
  onSelectSpot,
  onJumpToLatest,
  onRefresh,
  sx,
}: ReplayTimelinePanelProps) {
  const copy: ReplayTimelineCopy = getReplayTimelineCopy(locale);
  const tone = getStateTone(state, locale);
  const isEmpty = state === "idle" && items.length === 0;
  const rlAggregate = buildRlAggregateSummary(items);
  const selectedItem =
    items.find((item) => (selectedSpotId ? item.id === selectedSpotId : item.selected === true)) ?? items[0];

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
            radial-gradient(circle at bottom left, ${alpha(theme.palette.secondary.main, 0.1)}, transparent 28%),
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
                {copy.reviewTitle}
              </Typography>
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
              <Chip
                label={copy.spots(items.length)}
                variant="outlined"
                sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
              />
            </Stack>
          </Stack>

          {state === "loading" ? <LinearProgress color="secondary" /> : null}

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
                  icon={<TimelineRoundedIcon fontSize="small" />}
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
              {state !== "loading" ? null : (
                <Alert severity="info" variant="outlined">
                  {loadingMessage}
                </Alert>
              )}

              <RlAggregateCard summary={rlAggregate} copy={copy} locale={locale} />

              <Box
                sx={{
                  display: "grid",
                  gap: 2,
                  gridTemplateColumns: { xs: "minmax(0, 1fr)", xl: "minmax(0, 1.35fr) minmax(280px, 0.9fr)" },
                  alignItems: "start",
                }}
              >
                <Stack spacing={1.75}>
                  {items.map((item) => (
                    <TimelineSpotCard
                      key={item.id}
                      item={item}
                      selected={selectedSpotId ? selectedSpotId === item.id || item.selected === true : item.selected === true}
                      onSelect={onSelectSpot}
                      copy={copy}
                    />
                  ))}
                </Stack>

                <Stack
                  spacing={1.5}
                  sx={(theme) => ({
                    p: 1.75,
                    borderRadius: 4,
                    position: { xl: "sticky" },
                    top: { xl: 20 },
                    border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                    background:
                      theme.palette.mode === "dark"
                        ? "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02))"
                        : "linear-gradient(180deg, rgba(16,24,40,0.03), rgba(16,24,40,0.015))",
                  })}
                >
                  <Box>
                    <Typography variant="overline" color="text.secondary">
                      {copy.selectedDetailTitle}
                    </Typography>
                    <Typography variant="subtitle1" sx={{ mt: 0.35 }}>
                      {selectedItem?.title ?? copy.selectedDetailEmpty}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                      {selectedItem?.note ?? copy.selectedDetailSubtitle}
                    </Typography>
                  </Box>

                  {selectedItem ? (
                    <>
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        {selectedItem.street ? <Chip size="small" label={selectedItem.street} variant="outlined" /> : null}
                        {selectedItem.action ? <Chip size="small" label={selectedItem.action} color="primary" /> : null}
                        {selectedItem.result ? <Chip size="small" label={selectedItem.result} color="success" variant="outlined" /> : null}
                        {selectedItem.impactScore !== undefined ? (
                          <Chip
                            size="small"
                            label={`${selectedItem.impactLabel ?? "Impact"} ${formatImpactScore(selectedItem.impactScore)}`}
                            color="warning"
                            variant="outlined"
                          />
                        ) : null}
                        {selectedItem.confidence ? <Chip size="small" label={`${copy.confidence} ${selectedItem.confidence}`} variant="outlined" /> : null}
                        {selectedItem.rlDiffSummary?.deltaEv ? (
                          <Chip size="small" label={`${copy.rlDiff} ${selectedItem.rlDiffSummary.deltaEv}`} color="secondary" variant="outlined" />
                        ) : null}
                        {selectedItem.rlDiffSummary?.actionShift ? (
                          <Chip size="small" label={selectedItem.rlDiffSummary.actionShift} variant="outlined" />
                        ) : null}
                        {selectedItem.rlDiffSummary?.confidenceShift ? (
                          <Chip size="small" label={selectedItem.rlDiffSummary.confidenceShift} variant="outlined" />
                        ) : null}
                      </Stack>
                      <DetailBlock title={copy.spotBlock} rows={selectedItem.spotDetails ?? []} />
                      <DetailBlock title={copy.gateBlock} rows={selectedItem.gateDetails ?? []} />
                      <DetailBlock title={copy.traceBlock} rows={selectedItem.traceDetails ?? []} />
                      {selectedItem.incidents && selectedItem.incidents.length > 0 ? (
                        <Alert severity="warning" variant="outlined">
                          <strong>{copy.incidents}:</strong> {selectedItem.incidents.join(" · ")}
                        </Alert>
                      ) : null}
                    </>
                  ) : (
                    <Alert severity="info" variant="outlined">
                      {copy.selectedDetailEmpty}
                    </Alert>
                  )}
                </Stack>
              </Box>

              <Divider />

              <Stack
                direction={{ xs: "column", md: "row" }}
                spacing={1.25}
                justifyContent="space-between"
                alignItems={{ xs: "stretch", md: "center" }}
              >
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip
                    icon={<VisibilityRoundedIcon fontSize="small" />}
                    label={copy.queue}
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                  />
                  <Chip
                    icon={<HistoryRoundedIcon fontSize="small" />}
                    label={copy.history}
                    variant="outlined"
                    sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })}
                  />
                </Stack>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap justifyContent={{ xs: "stretch", md: "flex-end" }}>
                  <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={onRefresh} disabled={!onRefresh}>
                    {copy.refresh}
                  </Button>
                  <Button variant="contained" startIcon={<PlayCircleOutlineRoundedIcon />} onClick={onJumpToLatest} disabled={!onJumpToLatest}>
                    {copy.latest}
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

export default ReplayTimelinePanel;
