import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  Stack,
  Typography,
  type SxProps,
  type Theme,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import type { BotCockpitPayload } from "../../../lib/botCockpit";
import { getRuntimeMetricsCopy } from "../../../lib/workstationI18n";

export interface RuntimeMetricsCardProps {
  payload: BotCockpitPayload;
  locale?: "en" | "fr";
  title?: string;
  subtitle?: string;
  loading?: boolean;
  sx?: SxProps<Theme>;
}

type RuntimeRow = {
  label: string;
  value: string;
  helper?: string;
};

function formatPercent(value: number, digits = 0) {
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(digits)}%`;
}

function formatMs(value: number) {
  return `${Math.round(value)} ms`;
}

function formatRate(value: number) {
  return `${value.toFixed(1)}/min`;
}

function formatUptime(ms: number) {
  if (ms <= 0) {
    return "0s";
  }
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) {
    return `${minutes}m ${seconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return `${hours}h ${restMinutes}m`;
}

function prettify(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function MetricBlock({
  label,
  value,
  helper,
}: RuntimeRow): JSX.Element {
  return (
    <Box
      sx={(theme) => ({
        borderRadius: 2.5,
        border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
        background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.05 : 0.025),
        px: 1.5,
        py: 1.25,
      })}
    >
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" sx={{ mt: 0.4, lineHeight: 1.1 }}>
        {value}
      </Typography>
      {helper ? (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.35, display: "block" }}>
          {helper}
        </Typography>
      ) : null}
    </Box>
  );
}

function RowSection({
  title,
  rows,
}: {
  title: string;
  rows: RuntimeRow[];
}): JSX.Element {
  return (
    <Box
      sx={(theme) => ({
        borderRadius: 3,
        border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
        overflow: "hidden",
      })}
    >
      <Box
        sx={(theme) => ({
          px: 1.75,
          py: 1.15,
          borderBottom: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
          background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.05 : 0.025),
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
            sx={{ px: 1.75, py: 1.1 }}
          >
            <Box>
              <Typography variant="body2" color="text.secondary">
                {row.label}
              </Typography>
              {row.helper ? (
                <Typography variant="caption" color="text.secondary">
                  {row.helper}
                </Typography>
              ) : null}
            </Box>
            <Typography variant="body2" sx={{ fontWeight: 700, textAlign: "right" }}>
              {row.value}
            </Typography>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}

export function RuntimeMetricsCard({
  payload,
  locale = "en",
  title,
  subtitle,
  loading = false,
  sx,
}: RuntimeMetricsCardProps): JSX.Element {
  const baseCopy = getRuntimeMetricsCopy(locale);
  const copy = {
    ...baseCopy,
    title: title ?? baseCopy.title,
    subtitle: subtitle ?? baseCopy.subtitle,
  };

  const healthLabel = payload.state === "offline"
    ? copy.offline
    : payload.state === "degraded" || !payload.runtime.healthy
      ? copy.degraded
      : copy.healthy;

  const topMetrics: RuntimeRow[] = [
    {
      label: copy.decisions,
      value: String(payload.runtime.metrics.decisionCount),
      helper: `${payload.runtime.metrics.windowSize} ${copy.samples}`,
    },
    {
      label: copy.latency,
      value: formatMs(payload.runtime.metrics.rollingLatencyMs),
      helper: payload.runtime.status,
    },
    {
      label: copy.blockRate,
      value: formatPercent(payload.runtime.metrics.blockRate, 0),
      helper: `${payload.runtime.metrics.blockedCount} ${copy.blocked.toLowerCase()}`,
    },
    {
      label: copy.fallbackRate,
      value: formatPercent(payload.runtime.metrics.fallbackRate, 0),
      helper: `${payload.runtime.metrics.fallbackCount} ${copy.fallback.toLowerCase()}`,
    },
  ];

  const decisionFlowRows: RuntimeRow[] = [
    { label: copy.decisions, value: String(payload.runtime.metrics.decisionCount) },
    { label: copy.blocked, value: String(payload.runtime.metrics.blockedCount) },
    { label: copy.fallback, value: String(payload.runtime.metrics.fallbackCount) },
    { label: copy.rate, value: formatRate(payload.runtime.metrics.decisionRate) },
    {
      label: copy.window,
      value: `${payload.runtime.metrics.windowSize}`,
      helper: `${payload.runtime.metrics.windowSize} ${copy.samples}`,
    },
  ];

  const profileRows: RuntimeRow[] = [
    { label: copy.runtime, value: payload.runtime.runtime },
    { label: copy.transport, value: payload.transport.source },
    { label: copy.status, value: prettify(payload.runtime.status) },
    { label: copy.uptime, value: formatUptime(payload.runtime.uptimeMs) },
    { label: copy.provider, value: payload.runtime.llm.providerMode },
    { label: copy.privacy, value: prettify(payload.runtime.llm.privacyMode) },
    {
      label: copy.httpFallback,
      value: payload.runtime.httpFallbackEnabled ? copy.enabled : copy.disabled,
    },
    {
      label: copy.devMode,
      value: payload.runtime.devMode ? copy.enabled : copy.disabled,
    },
  ];

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
      {loading ? <LinearProgress /> : null}
      <CardContent sx={{ p: { xs: 2.25, md: 2.75 } }}>
        <Stack spacing={2.25}>
          <Box>
            <Typography variant="overline" color="text.secondary">
              {copy.eyebrow}
            </Typography>
            <Typography variant="h5">{copy.title}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {copy.subtitle}
            </Typography>
          </Box>

          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
            <Chip
              label={`${copy.status} · ${healthLabel}`}
              color={healthLabel === copy.healthy ? "success" : healthLabel === copy.degraded ? "warning" : "default"}
              variant="outlined"
              size="small"
            />
            <Chip label={`${copy.runtime} · ${payload.runtime.runtime}`} variant="outlined" size="small" />
            <Chip
              label={`${copy.assistant} · ${payload.runtime.llm.enabled ? copy.on : copy.off}`}
              variant="outlined"
              size="small"
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
            {topMetrics.map((metric) => (
              <MetricBlock key={metric.label} {...metric} />
            ))}
          </Box>

          <Box
            sx={{
              display: "grid",
              gap: 1.5,
              gridTemplateColumns: {
                xs: "1fr",
                md: "minmax(0, 1fr) minmax(0, 1fr)",
              },
            }}
          >
            <RowSection title={copy.decisionFlow} rows={decisionFlowRows} />
            <RowSection title={copy.runtimeProfile} rows={profileRows} />
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

export default RuntimeMetricsCard;
