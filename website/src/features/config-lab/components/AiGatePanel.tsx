import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Slider,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import {
  AI_GATE_PRESETS,
  applyAiGatePreset,
  isLoopbackUrl,
  type AiGateConfig,
  type AiGateMode,
  type AiGatePresetId,
} from "../../../lib/aiGateConfig";
import { getAiGateCopy } from "../../../lib/workstationI18n";
import type { JevGateLanTestState } from "./JevGatePanel";

export interface AiGatePanelProps {
  locale?: "en" | "fr";
  value: AiGateConfig;
  disabled?: boolean;
  statusText?: string | null;
  lanTest?: JevGateLanTestState;
  onChange: (next: AiGateConfig) => void;
  onReset?: () => void;
  onTestLan?: () => void;
  /** Délègue au JevGatePanel legacy (alias compat : rien ne casse). */
  renderLegacyJev?: boolean;
}

function SectionTitle({ children }: { children: string }) {
  return (
    <Typography
      variant="caption"
      sx={{ color: "text.secondary", textTransform: "uppercase", letterSpacing: 1 }}
    >
      {children}
    </Typography>
  );
}

function ThresholdSlider({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  disabled: boolean;
  onChange: (next: number) => void;
}) {
  return (
    <Stack spacing={0.5}>
      <Typography variant="body2">
        {label}: {value.toFixed(2)}
      </Typography>
      <Slider
        value={value}
        min={0}
        max={1}
        step={0.05}
        disabled={disabled}
        onChange={(_, next) =>
          onChange(typeof next === "number" ? next : next[0])
        }
      />
    </Stack>
  );
}

export function AiGatePanel({
  locale = "en",
  value,
  disabled = false,
  statusText = null,
  lanTest = { status: "idle", message: "" },
  onChange,
  onReset,
  onTestLan,
}: AiGatePanelProps) {
  const copy = getAiGateCopy(locale);
  const lanConfigured = value.djev.lanUrl.trim().length > 0;
  const wanRefused = value.offlineMode && !isLoopbackUrl(value.djev.baseUrl);

  const applyPreset = (preset: AiGatePresetId) => {
    onChange(applyAiGatePreset(value, preset));
  };

  const patchMode = (mode: AiGateMode) => {
    onChange({
      ...value,
      djev: { ...value.djev, mode },
      jev: { ...value.jev, mode },
    });
  };

  return (
    <Card
      elevation={0}
      sx={(theme) => ({
        borderRadius: 4,
        overflow: "hidden",
        border: 1,
        borderColor: "divider",
        background:
          theme.palette.mode === "dark"
            ? "linear-gradient(180deg, rgba(19,25,35,0.96) 0%, rgba(13,18,28,0.92) 100%)"
            : "linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(245,248,252,0.98) 100%)",
        boxShadow: `0 18px 60px ${alpha(theme.palette.common.black, theme.palette.mode === "dark" ? 0.22 : 0.08)}`,
      })}
    >
      <CardContent sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={2}>
            <Box>
              <Typography variant="overline" sx={{ letterSpacing: 1.8, color: "text.secondary" }}>
                {copy.kicker}
              </Typography>
              <Typography variant="h5" sx={{ fontWeight: 800, letterSpacing: -0.4 }}>
                {copy.title}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 760 }}>
                {copy.subtitle}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip
                label={`${copy.provider}: ${value.provider}`}
                variant="outlined"
                color={value.provider === "auto" ? "primary" : "info"}
              />
              {value.offlineMode ? (
                <Chip label="offline" variant="outlined" color="warning" />
              ) : null}
              <Button variant="outlined" disabled={disabled} onClick={onReset}>
                {copy.reset}
              </Button>
            </Stack>
          </Stack>

          <Stack spacing={1}>
            <SectionTitle>{copy.provider}</SectionTitle>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <FormControl size="small" sx={{ minWidth: 200 }} disabled={disabled}>
                <InputLabel>{copy.provider}</InputLabel>
                <Select
                  value={value.provider}
                  label={copy.provider}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      provider: event.target.value as AiGateConfig["provider"],
                    })
                  }
                >
                  <MenuItem value="auto">auto</MenuItem>
                  <MenuItem value="jev">{copy.jev}</MenuItem>
                  <MenuItem value="djev">{copy.djev}</MenuItem>
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 200 }} disabled={disabled}>
                <InputLabel>{copy.mode}</InputLabel>
                <Select
                  value={value.djev.mode}
                  label={copy.mode}
                  onChange={(event) => patchMode(event.target.value as AiGateMode)}
                >
                  <MenuItem value="observer">observer</MenuItem>
                  <MenuItem value="enforcing">enforcing</MenuItem>
                  <MenuItem value="off">off</MenuItem>
                </Select>
              </FormControl>
            </Stack>
          </Stack>

          <Stack spacing={1}>
            <SectionTitle>presets</SectionTitle>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {AI_GATE_PRESETS.map((preset) => (
                <Chip
                  key={preset}
                  label={
                    preset === "lan"
                      ? copy.presetLan
                      : preset === "offline"
                        ? copy.presetOffline
                        : copy.presetCloud
                  }
                  color={
                    (preset === "offline" && value.offlineMode) ||
                    (preset === "cloud" && value.cloudFallback)
                      ? "primary"
                      : "default"
                  }
                  variant="outlined"
                  onClick={() => !disabled && applyPreset(preset)}
                />
              ))}
            </Stack>
            <FormControlLabel
              control={
                <Switch
                  checked={value.offlineMode}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange({ ...value, offlineMode: event.target.checked })
                  }
                />
              }
              label={copy.offlineMode}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={value.cloudFallback}
                  disabled={disabled || value.offlineMode}
                  onChange={(event) =>
                    onChange({ ...value, cloudFallback: event.target.checked })
                  }
                />
              }
              label={copy.cloudFallback}
            />
            {wanRefused ? (
              <Typography variant="caption" color="warning.main">
                {copy.wanRefused}
              </Typography>
            ) : null}
          </Stack>

          <Stack spacing={1.5}>
            <SectionTitle>{copy.djev}</SectionTitle>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
              <TextField
                size="small"
                label={copy.baseUrl}
                value={value.djev.baseUrl}
                disabled={disabled}
                onChange={(event) =>
                  onChange({
                    ...value,
                    djev: { ...value.djev, baseUrl: event.target.value },
                  })
                }
                fullWidth
              />
              <TextField
                size="small"
                label={copy.model}
                value={value.djev.model}
                disabled={disabled}
                onChange={(event) =>
                  onChange({
                    ...value,
                    djev: { ...value.djev, model: event.target.value },
                  })
                }
                fullWidth
              />
            </Stack>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
              <TextField
                size="small"
                label={copy.lanUrl}
                value={value.djev.lanUrl}
                disabled={disabled}
                placeholder="http://127.0.0.1:4000"
                onChange={(event) =>
                  onChange({
                    ...value,
                    djev: { ...value.djev, lanUrl: event.target.value },
                  })
                }
                fullWidth
              />
              <TextField
                size="small"
                label={copy.cloudUrl}
                value={value.djev.cloudUrl}
                disabled={disabled}
                onChange={(event) =>
                  onChange({
                    ...value,
                    djev: { ...value.djev, cloudUrl: event.target.value },
                  })
                }
                fullWidth
              />
            </Stack>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
              <TextField
                size="small"
                label={copy.apiKeyEnv}
                value={value.djev.apiKeyEnv}
                disabled={disabled}
                helperText={copy.apiKeyHint}
                onChange={(event) =>
                  onChange({
                    ...value,
                    djev: { ...value.djev, apiKeyEnv: event.target.value },
                  })
                }
                fullWidth
              />
              <TextField
                size="small"
                type="number"
                label={copy.timeout}
                value={value.djev.timeoutS}
                disabled={disabled}
                inputProps={{ min: 0.5, step: 0.5 }}
                onChange={(event) =>
                  onChange({
                    ...value,
                    djev: { ...value.djev, timeoutS: Number(event.target.value) },
                  })
                }
                fullWidth
              />
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Button
                variant="outlined"
                size="small"
                disabled={disabled || !lanConfigured || lanTest.status === "running"}
                onClick={onTestLan}
              >
                {lanTest.status === "running" ? copy.testing : copy.testLan}
              </Button>
              {lanTest.message ? (
                <Typography
                  variant="caption"
                  color={lanTest.status === "error" ? "error.main" : "success.main"}
                >
                  {lanTest.message}
                </Typography>
              ) : null}
            </Stack>
          </Stack>

          <Stack spacing={1}>
            <SectionTitle>{copy.thresholds}</SectionTitle>
            <ThresholdSlider
              label={`${copy.upgrade} (djev)`}
              value={value.djev.minUpgradeConfidence}
              disabled={disabled}
              onChange={(next) =>
                onChange({
                  ...value,
                  djev: { ...value.djev, minUpgradeConfidence: next },
                })
              }
            />
            <ThresholdSlider
              label={`${copy.downgrade} (djev)`}
              value={value.djev.minDowngradeConfidence}
              disabled={disabled}
              onChange={(next) =>
                onChange({
                  ...value,
                  djev: { ...value.djev, minDowngradeConfidence: next },
                })
              }
            />
            <ThresholdSlider
              label={`${copy.risky} (djev)`}
              value={value.djev.riskyThreshold}
              disabled={disabled}
              onChange={(next) =>
                onChange({
                  ...value,
                  djev: { ...value.djev, riskyThreshold: next },
                })
              }
            />
            <ThresholdSlider
              label={`${copy.upgrade} (jev)`}
              value={value.jev.minUpgradeConfidence}
              disabled={disabled}
              onChange={(next) =>
                onChange({
                  ...value,
                  jev: { ...value.jev, minUpgradeConfidence: next },
                })
              }
            />
            <ThresholdSlider
              label={`${copy.downgrade} (jev)`}
              value={value.jev.minDowngradeConfidence}
              disabled={disabled}
              onChange={(next) =>
                onChange({
                  ...value,
                  jev: { ...value.jev, minDowngradeConfidence: next },
                })
              }
            />
            <ThresholdSlider
              label={`${copy.risky} (jev)`}
              value={value.jev.riskyThreshold}
              disabled={disabled}
              onChange={(next) =>
                onChange({
                  ...value,
                  jev: { ...value.jev, riskyThreshold: next },
                })
              }
            />
          </Stack>

          {statusText ? (
            <Typography variant="caption" color="text.secondary">
              {statusText}
            </Typography>
          ) : null}
        </Stack>
      </CardContent>
    </Card>
  );
}
