import type { ReactElement, ReactNode } from "react";
import {
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
import AutorenewRoundedIcon from "@mui/icons-material/AutorenewRounded";
import CameraswitchRoundedIcon from "@mui/icons-material/CameraswitchRounded";
import EditRoundedIcon from "@mui/icons-material/EditRounded";
import PauseCircleRoundedIcon from "@mui/icons-material/PauseCircleRounded";
import PlayCircleRoundedIcon from "@mui/icons-material/PlayCircleRounded";
import RadioButtonCheckedRoundedIcon from "@mui/icons-material/RadioButtonCheckedRounded";
import SecurityRoundedIcon from "@mui/icons-material/SecurityRounded";
import VisibilityOffRoundedIcon from "@mui/icons-material/VisibilityOffRounded";
import { getOperatorConsoleCopy } from "../../../lib/workstationI18n";

export type OperatorConsoleMode =
  | "live"
  | "paused"
  | "shadow"
  | "manual_override"
  | "monitoring";

export type OperatorAlertTone = "info" | "success" | "warning" | "error";

export interface OperatorAlert {
  id?: string;
  label: string;
  tone?: OperatorAlertTone;
  detail?: string;
}

export interface OperatorMetric {
  label: string;
  value: string;
  helper?: string;
  icon?: ReactNode;
}

export interface OperatorConsolePanelProps {
  title?: string;
  subtitle?: string;
  locale?: "en" | "fr";
  mode?: OperatorConsoleMode;
  paused?: boolean;
  shadowModeActive?: boolean;
  manualOverrideActive?: boolean;
  alerts?: OperatorAlert[];
  metrics?: OperatorMetric[];
  statusLabel?: string;
  statusDetail?: string;
  operatorLabel?: string;
  onRefresh?: () => void;
  onCaptureSpot?: () => void;
  onToggleShadowMode?: () => void;
  onToggleManualOverride?: () => void;
  onTogglePaused?: () => void;
  refreshLabel?: string;
  captureLabel?: string;
  shadowLabel?: string;
  manualOverrideLabel?: string;
  pauseLabel?: string;
  resumeLabel?: string;
  disabled?: boolean;
  sx?: SxProps<Theme>;
}

type ModeTone = {
  label: string;
  color: "default" | "primary" | "secondary" | "success" | "warning" | "error";
  icon: ReactElement;
  description: string;
};

const DEFAULT_TITLE = "Operator Console";
const DEFAULT_SUBTITLE =
  "Keep the cockpit responsive, visible, and ready to recover. The controls stay local and never block the solver path.";

function getModeTone(
  mode: OperatorConsoleMode,
  paused: boolean,
  shadowModeActive: boolean,
  manualOverrideActive: boolean,
  locale: "en" | "fr"
): ModeTone {
  const copy = getOperatorConsoleCopy(locale);
  if (paused || mode === "paused") {
    return {
      label: copy.paused,
      color: "warning",
      icon: <PauseCircleRoundedIcon fontSize="small" />,
      description: copy.pausedDescription,
    };
  }

  if (manualOverrideActive || mode === "manual_override") {
    return {
      label: copy.manualOverride,
      color: "secondary",
      icon: <EditRoundedIcon fontSize="small" />,
      description: copy.manualOverrideDescription,
    };
  }

  if (shadowModeActive || mode === "shadow") {
    return {
      label: copy.shadowMode,
      color: "primary",
      icon: <VisibilityOffRoundedIcon fontSize="small" />,
      description: copy.shadowModeDescription,
    };
  }

  if (mode === "monitoring") {
    return {
      label: copy.monitoring,
      color: "default",
      icon: <SecurityRoundedIcon fontSize="small" />,
      description: copy.monitoringDescription,
    };
  }

  return {
    label: copy.live,
    color: "success",
    icon: <RadioButtonCheckedRoundedIcon fontSize="small" />,
    description: copy.liveDescription,
  };
}

function getAlertColor(tone: OperatorAlertTone): "default" | "primary" | "secondary" | "success" | "warning" | "error" {
  return tone === "success" ? "success" : tone === "error" ? "error" : tone === "warning" ? "warning" : tone === "info" ? "primary" : "default";
}

function SummaryMetric({
  label,
  value,
  helper,
  icon,
}: {
  label: string;
  value: string;
  helper?: string;
  icon?: ReactNode;
}) {
  return (
    <Box
      sx={(theme) => ({
        flex: "1 1 180px",
        minWidth: 0,
        borderRadius: 3,
        border: `1px solid ${alpha(theme.palette.common.white, 0.08)}`,
        background:
          "linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02))",
        px: 2,
        py: 1.75,
      })}
    >
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        <Box
          sx={(theme) => ({
            mt: 0.25,
            width: 34,
            height: 34,
            display: "grid",
            placeItems: "center",
            borderRadius: "50%",
            bgcolor: alpha(theme.palette.primary.main, 0.12),
            color: theme.palette.primary.main,
            flex: "0 0 auto",
          })}
        >
          {icon ?? <SecurityRoundedIcon fontSize="small" />}
        </Box>
        <Stack spacing={0.35} minWidth={0}>
          <Typography variant="caption" color="text.secondary">
            {label}
          </Typography>
          <Typography variant="h6" sx={{ lineHeight: 1.05 }}>
            {value}
          </Typography>
          {helper ? (
            <Typography variant="body2" color="text.secondary">
              {helper}
            </Typography>
          ) : null}
        </Stack>
      </Stack>
    </Box>
  );
}

export function OperatorConsolePanel({
  title,
  subtitle,
  locale = "en",
  mode = "live",
  paused = false,
  shadowModeActive = false,
  manualOverrideActive = false,
  alerts = [],
  metrics = [],
  statusLabel,
  statusDetail,
  operatorLabel = "Operator",
  onRefresh,
  onCaptureSpot,
  onToggleShadowMode,
  onToggleManualOverride,
  onTogglePaused,
  refreshLabel = "Refresh",
  captureLabel = "Capture",
  shadowLabel = "Shadow",
  manualOverrideLabel = "Manual override",
  pauseLabel = "Pause",
  resumeLabel = "Resume",
  disabled = false,
  sx,
}: OperatorConsolePanelProps) {
  const copy = getOperatorConsoleCopy(locale);
  const resolvedTitle = title ?? copy.defaultTitle;
  const resolvedSubtitle = subtitle ?? copy.defaultSubtitle;
  const tone = getModeTone(mode, paused, shadowModeActive, manualOverrideActive, locale);
  const liveStateLabel = paused || mode === "paused" ? copy.paused : copy.live;
  const actionStateLabel =
    statusLabel ||
    (manualOverrideActive || mode === "manual_override"
      ? copy.manualActive
      : shadowModeActive || mode === "shadow"
        ? copy.shadowActive
        : paused || mode === "paused"
          ? copy.capturePaused
          : copy.cockpitLive);
  const showPrimaryActions = Boolean(
    onRefresh || onCaptureSpot || onToggleShadowMode || onToggleManualOverride || onTogglePaused
  );

  return (
    <Card
      sx={[
        (theme) => ({
          borderRadius: 5,
          overflow: "hidden",
          position: "relative",
          border: `1px solid ${alpha(theme.palette.common.white, 0.08)}`,
          background:
            "linear-gradient(180deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.03) 100%)",
          "&::before": {
            content: '""',
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            background:
              "radial-gradient(circle at top right, rgba(125,211,252,0.12), transparent 38%), radial-gradient(circle at bottom left, rgba(59,130,246,0.14), transparent 34%)",
          },
        }),
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
    >
      <CardContent sx={{ position: "relative", zIndex: 1, p: { xs: 2.25, md: 3 } }}>
        <Stack spacing={2.5}>
          <Stack
            direction={{ xs: "column", md: "row" }}
            spacing={2}
            alignItems={{ xs: "flex-start", md: "center" }}
            justifyContent="space-between"
          >
            <Stack spacing={1} minWidth={0}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography variant="overline" color="primary.main" sx={{ letterSpacing: "0.16em" }}>
                  {operatorLabel}
                </Typography>
                <Chip
                  label={liveStateLabel}
                  color={paused || mode === "paused" ? "warning" : "success"}
                  size="small"
                  icon={tone.icon}
                />
                {statusLabel ? (
                  <Chip
                    label={statusLabel}
                    size="small"
                    variant="outlined"
                    sx={{ borderColor: "rgba(255,255,255,0.12)" }}
                  />
                ) : null}
              </Stack>
              <Stack spacing={0.5} minWidth={0}>
                <Typography variant="h5" sx={{ fontWeight: 800, letterSpacing: "-0.02em" }}>
                {resolvedTitle}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 820 }}>
                {resolvedSubtitle}
                </Typography>
              </Stack>
            </Stack>

            <Stack spacing={0.75} alignItems={{ xs: "flex-start", md: "flex-end" }}>
              <Tooltip title={tone.description} placement="top">
                <Chip
                  label={tone.label}
                  color={tone.color}
                  icon={tone.icon}
                  variant="outlined"
                  sx={{ borderColor: "rgba(255,255,255,0.12)" }}
                />
              </Tooltip>
              {statusDetail ? (
                <Typography variant="body2" color="text.secondary" sx={{ textAlign: { xs: "left", md: "right" } }}>
                  {statusDetail}
                </Typography>
              ) : null}
              {!statusDetail ? (
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ textAlign: { xs: "left", md: "right" }, maxWidth: 340 }}
                >
                  {actionStateLabel}
                </Typography>
              ) : null}
            </Stack>
          </Stack>

          {paused || mode === "paused" ? null : (
            <LinearProgress
              color={manualOverrideActive || mode === "manual_override" ? "secondary" : shadowModeActive || mode === "shadow" ? "primary" : "success"}
              sx={{
                height: 8,
                borderRadius: 99,
                bgcolor: "rgba(255,255,255,0.06)",
              }}
            />
          )}

          {alerts.length > 0 ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {alerts.map((alert, index) => {
                const key = alert.id ?? `${alert.label}-${index}`;
                const chip = (
                  <Chip
                    key={key}
                    label={alert.label}
                    color={getAlertColor(alert.tone ?? "info")}
                    variant="outlined"
                    sx={{ borderColor: "rgba(255,255,255,0.12)" }}
                  />
                );

                return alert.detail ? <Tooltip key={key} title={alert.detail}>{chip}</Tooltip> : chip;
              })}
            </Stack>
          ) : null}

          <Stack
            direction={{ xs: "column", lg: "row" }}
            spacing={2}
            alignItems={{ xs: "stretch", lg: "flex-start" }}
          >
            <Stack spacing={1.5} flex={1}>
              <Typography variant="subtitle2" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.12em" }}>
                {copy.controls}
              </Typography>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} useFlexGap flexWrap="wrap">
                <Button
                  variant="contained"
                  startIcon={<AutorenewRoundedIcon />}
                  onClick={onRefresh}
                  disabled={disabled || !onRefresh}
                >
                  {refreshLabel}
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<CameraswitchRoundedIcon />}
                  onClick={onCaptureSpot}
                  disabled={disabled || !onCaptureSpot}
                >
                  {captureLabel}
                </Button>
                <Button
                  variant={shadowModeActive || mode === "shadow" ? "contained" : "outlined"}
                  color={shadowModeActive || mode === "shadow" ? "primary" : "inherit"}
                  startIcon={<VisibilityOffRoundedIcon />}
                  onClick={onToggleShadowMode}
                  disabled={disabled || !onToggleShadowMode}
                >
                  {shadowLabel}
                </Button>
                <Button
                  variant={manualOverrideActive || mode === "manual_override" ? "contained" : "outlined"}
                  color={manualOverrideActive || mode === "manual_override" ? "secondary" : "inherit"}
                  startIcon={<EditRoundedIcon />}
                  onClick={onToggleManualOverride}
                  disabled={disabled || !onToggleManualOverride}
                >
                  {manualOverrideLabel}
                </Button>
                <Button
                  variant={paused || mode === "paused" ? "contained" : "outlined"}
                  color={paused || mode === "paused" ? "warning" : "inherit"}
                  startIcon={paused || mode === "paused" ? <PlayCircleRoundedIcon /> : <PauseCircleRoundedIcon />}
                  onClick={onTogglePaused}
                  disabled={disabled || !onTogglePaused}
                >
                  {paused || mode === "paused" ? resumeLabel : pauseLabel}
                </Button>
              </Stack>

              {!showPrimaryActions ? (
                <Box
                  sx={(theme) => ({
                    p: 2,
                    borderRadius: 3,
                    border: `1px dashed ${alpha(theme.palette.common.white, 0.14)}`,
                    bgcolor: alpha(theme.palette.common.white, 0.02),
                  })}
                >
                    <Typography variant="body2" color="text.secondary">
                     {copy.noCallbacks}
                    </Typography>
                  </Box>
                ) : null}
              </Stack>

              <Stack spacing={1.5} flex={1.1}>
                <Typography variant="subtitle2" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: "0.12em" }}>
                  {copy.stateSummary}
                </Typography>
              <Stack direction="row" spacing={1.25} useFlexGap flexWrap="wrap">
                <Chip
                  label={liveStateLabel}
                  color={paused || mode === "paused" ? "warning" : "success"}
                  icon={paused || mode === "paused" ? <PauseCircleRoundedIcon fontSize="small" /> : <PlayCircleRoundedIcon fontSize="small" />}
                />
                <Chip
                  label={
                    shadowModeActive || mode === "shadow"
                      ? copy.shadowEnabled
                      : copy.shadowDisabled
                  }
                  color={shadowModeActive || mode === "shadow" ? "primary" : "default"}
                  variant="outlined"
                />
                <Chip
                  label={
                    manualOverrideActive || mode === "manual_override"
                      ? copy.manualMode
                      : copy.automation
                  }
                  color={manualOverrideActive || mode === "manual_override" ? "secondary" : "default"}
                  variant="outlined"
                />
              </Stack>

              <Divider />

              <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap">
                {metrics.length > 0 ? (
                  metrics.map((metric, index) => (
                    <SummaryMetric
                      key={`${metric.label}-${index}`}
                      label={metric.label}
                      value={metric.value}
                      helper={metric.helper}
                      icon={metric.icon}
                    />
                  ))
                ) : (
                  <Box
                    sx={(theme) => ({
                      width: "100%",
                      p: 2,
                      borderRadius: 3,
                      border: `1px solid ${alpha(theme.palette.common.white, 0.08)}`,
                      bgcolor: alpha(theme.palette.common.white, 0.02),
                    })}
                  >
                    <Typography variant="body2" color="text.secondary">
                      {copy.metricsHint}
                    </Typography>
                  </Box>
                )}
              </Stack>
            </Stack>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

export default OperatorConsolePanel;
