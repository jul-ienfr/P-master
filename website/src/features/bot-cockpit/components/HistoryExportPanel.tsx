import DownloadRoundedIcon from "@mui/icons-material/DownloadRounded";
import SaveRoundedIcon from "@mui/icons-material/SaveRounded";
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Stack,
  Typography,
  type SxProps,
  type Theme,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { getHistoryExportCopy } from "../../../lib/workstationI18n";
import type { CockpitHistoryViewMode } from "../types";

export interface HistoryExportPanelProps {
  locale?: "en" | "fr";
  sourceLabel?: string;
  activeHistoryView?: CockpitHistoryViewMode;
  persistedCount?: number;
  runtimeCount?: number;
  combinedCount?: number;
  warningsCount?: number;
  incidentsCount?: number;
  currentAction?: string;
  tableName?: string;
  handId?: string;
  refreshedAt?: string;
  persistedAt?: string | null;
  latestEntries?: string[];
  onExport?: () => void;
  sx?: SxProps<Theme>;
}

type StatItem = {
  label: string;
  value: string;
  helper?: string;
};

function formatDateTime(value: string | null | undefined, locale: "en" | "fr") {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function prettifyLabel(value: string | null | undefined, fallback: string) {
  if (!value || value.trim().length === 0) {
    return fallback;
  }

  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function MetricGrid({ items }: { items: StatItem[] }) {
  return (
    <Box
      sx={{
        display: "grid",
        gap: 1.25,
        gridTemplateColumns: {
          xs: "1fr 1fr",
          md: "repeat(4, minmax(0, 1fr))",
        },
      }}
    >
      {items.map((item) => (
        <Box
          key={item.label}
          sx={(theme) => ({
            borderRadius: 2.5,
            border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
            background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.05 : 0.025),
            px: 1.5,
            py: 1.25,
          })}
        >
          <Typography variant="caption" color="text.secondary">
            {item.label}
          </Typography>
          <Typography variant="h6" sx={{ mt: 0.4, lineHeight: 1.1 }}>
            {item.value}
          </Typography>
          {item.helper ? (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.35, display: "block" }}>
              {item.helper}
            </Typography>
          ) : null}
        </Box>
      ))}
    </Box>
  );
}

export function HistoryExportPanel({
  locale = "en",
  sourceLabel,
  activeHistoryView = "combined",
  persistedCount = 0,
  runtimeCount = 0,
  combinedCount = 0,
  warningsCount = 0,
  incidentsCount = 0,
  currentAction,
  tableName,
  handId,
  refreshedAt,
  persistedAt,
  latestEntries = [],
  onExport,
  sx,
}: HistoryExportPanelProps): JSX.Element {
  const cardSx = {
    borderRadius: 5,
    overflow: "hidden",
  };
  const copy = getHistoryExportCopy(locale);

  const viewLabels: Record<CockpitHistoryViewMode, string> = {
    runtime: copy.runtime,
    persisted: copy.persisted,
    combined: copy.combined,
  };

  const stats: StatItem[] = [
    { label: copy.persisted, value: String(persistedCount) },
    { label: copy.runtime, value: String(runtimeCount) },
    { label: copy.combined, value: String(combinedCount) },
    { label: copy.warnings, value: String(warningsCount), helper: `${copy.incidents}: ${incidentsCount}` },
  ];

  return (
    <Card
      variant="outlined"
      sx={[
        cardSx,
        (theme) => ({
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
      <CardContent sx={{ p: { xs: 2.25, md: 2.75 } }}>
        <Stack spacing={2.5}>
          <Stack
            direction={{ xs: "column", md: "row" }}
            justifyContent="space-between"
            spacing={1.5}
            alignItems={{ xs: "flex-start", md: "center" }}
          >
            <Box>
              <Typography variant="overline" color="text.secondary">
                {copy.eyebrow}
              </Typography>
              <Typography variant="h5">{copy.title}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {copy.subtitle}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip icon={<SaveRoundedIcon />} label={copy.localBundle} color="primary" variant="outlined" />
              <Chip label={copy.savedLocally} size="small" />
              <Button
                variant="contained"
                color="primary"
                startIcon={<DownloadRoundedIcon />}
                onClick={onExport}
                disabled={!onExport}
              >
                {copy.exportJson}
              </Button>
            </Stack>
          </Stack>

          <MetricGrid items={stats} />

          <Box
            sx={(theme) => ({
              borderRadius: 3,
              border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
              background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
              px: 1.75,
              py: 1.5,
            })}
          >
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 1.25 }}>
              <Chip label={`${copy.currentView} · ${viewLabels[activeHistoryView]}`} size="small" color="primary" />
              {currentAction ? <Chip label={`${copy.action} · ${currentAction}`} size="small" variant="outlined" /> : null}
              {sourceLabel ? <Chip label={`${copy.source} · ${sourceLabel}`} size="small" variant="outlined" /> : null}
            </Stack>
            <Typography variant="body2" color="text.secondary">
              {copy.lastSaved}: {formatDateTime(persistedAt, locale)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {copy.refreshed}: {formatDateTime(refreshedAt, locale)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {copy.table}: {tableName || copy.unknown}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {copy.hand}: {handId || copy.unknown}
            </Typography>
          </Box>

          <Divider />

          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1.25 }}>
              {copy.latestEntries}
            </Typography>
            {latestEntries.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {copy.noEntries}
              </Typography>
            ) : (
              <Stack spacing={0.9}>
                {latestEntries.map((entry, index) => (
                  <Box
                    key={`${entry}-${index}`}
                    sx={(theme) => ({
                      borderRadius: 2.5,
                      border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                      background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.05 : 0.025),
                      px: 1.25,
                      py: 1,
                    })}
                  >
                    <Stack direction="row" spacing={1} alignItems="flex-start">
                      <Chip label={latestEntries.length - index} size="small" sx={{ minWidth: 32 }} />
                      <Typography variant="body2" sx={{ pt: 0.25 }}>
                        {prettifyLabel(entry, copy.unknown)}
                      </Typography>
                    </Stack>
                  </Box>
                ))}
              </Stack>
            )}
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

export default HistoryExportPanel;
