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
import type { ConfigLabJevConfig } from "../../../lib/jevGateConfig";
import { JEV_GATE_USAGES } from "../../../lib/jevGateConfig";
import type { ConfigLabJevBackend, ConfigLabJevDeployment, ConfigLabJevMode } from "../../../lib/configLab";
import { getJevGateCopy } from "../../../lib/workstationI18n";

export interface JevGateLanTestState {
  status: "idle" | "running" | "ok" | "error";
  message: string;
}

export interface JevGatePanelProps {
  locale?: "en" | "fr";
  value: ConfigLabJevConfig;
  disabled?: boolean;
  statusText?: string | null;
  lanTest?: JevGateLanTestState;
  onChange: (next: ConfigLabJevConfig) => void;
  onReset?: () => void;
  onTestLan?: () => void;
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

export function JevGatePanel({
  locale = "en",
  value,
  disabled = false,
  statusText = null,
  lanTest = { status: "idle", message: "" },
  onChange,
  onReset,
  onTestLan,
}: JevGatePanelProps) {
  const copy = getJevGateCopy(locale);
  const lanConfigured = value.lan.baseUrl.trim().length > 0;

  const patch = (overrides: Partial<ConfigLabJevConfig>) => {
    onChange({ ...value, ...overrides });
  };

  const patchLan = (overrides: Partial<ConfigLabJevConfig["lan"]>) => {
    onChange({ ...value, lan: { ...value.lan, ...overrides } });
  };

  const patchMultimodal = (overrides: Partial<ConfigLabJevConfig["multimodal"]>) => {
    onChange({ ...value, multimodal: { ...value.multimodal, ...overrides } });
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
                label={`${copy.mode}: ${value.mode}`}
                variant="outlined"
                color={value.mode === "enforcing" ? "warning" : "info"}
              />
              <Chip
                label={`${copy.deployment}: ${value.deployment}`}
                variant="outlined"
                color={value.deployment === "dual" ? "primary" : "default"}
              />
              <Button variant="outlined" disabled={disabled} onClick={onReset}>
                {copy.reset}
              </Button>
            </Stack>
          </Stack>

          <Stack spacing={1}>
            <SectionTitle>{copy.deployment}</SectionTitle>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {(["single", "dual"] as ConfigLabJevDeployment[]).map((option) => (
                <Chip
                  key={option}
                  label={option === "single" ? copy.single : copy.dual}
                  color={value.deployment === option ? "primary" : "default"}
                  variant={value.deployment === option ? "filled" : "outlined"}
                  onClick={() => !disabled && patch({ deployment: option })}
                />
              ))}
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {copy.deploymentHint}
            </Typography>
          </Stack>

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
            <FormControl size="small" fullWidth disabled={disabled}>
              <InputLabel>{copy.backend}</InputLabel>
              <Select
                value={value.backend}
                label={copy.backend}
                onChange={(event) => patch({ backend: event.target.value as ConfigLabJevBackend })}
              >
                <MenuItem value="cloud">cloud</MenuItem>
                <MenuItem value="local">local</MenuItem>
                <MenuItem value="auto">auto</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth disabled={disabled}>
              <InputLabel>{copy.mode}</InputLabel>
              <Select
                value={value.mode}
                label={copy.mode}
                onChange={(event) => patch({ mode: event.target.value as ConfigLabJevMode })}
              >
                <MenuItem value="observer">observer</MenuItem>
                <MenuItem value="enforcing">enforcing</MenuItem>
                <MenuItem value="off">off</MenuItem>
              </Select>
            </FormControl>
          </Stack>

          <Stack spacing={1}>
            <SectionTitle>{copy.thresholds}</SectionTitle>
            {(
              [
                { key: "minUpgradeConfidence", label: copy.upgrade },
                { key: "minDowngradeConfidence", label: copy.downgrade },
                { key: "riskyThreshold", label: copy.risky },
              ] as const
            ).map(({ key, label }) => (
              <Stack key={key} spacing={0.5}>
                <Typography variant="body2">
                  {label}: {value[key].toFixed(2)}
                </Typography>
                <Slider
                  value={value[key]}
                  min={0}
                  max={1}
                  step={0.05}
                  disabled={disabled}
                  onChange={(_, next) =>
                    patch({ [key]: typeof next === "number" ? next : next[0] } as Partial<ConfigLabJevConfig>)
                  }
                />
              </Stack>
            ))}
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip label={copy.failOpen} variant="outlined" color="success" />
              <Chip label={copy.cropsLiveLocked} variant="outlined" color="warning" />
            </Stack>
          </Stack>

          <Stack spacing={1.5}>
            <SectionTitle>{copy.lan}</SectionTitle>
            <TextField
              size="small"
              label={copy.lanUrl}
              value={value.lan.baseUrl}
              disabled={disabled}
              placeholder="http://192.168.1.20:4000"
              onChange={(event) => patchLan({ baseUrl: event.target.value })}
              fullWidth
            />
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
              <TextField
                size="small"
                label={copy.lanModel}
                value={value.lan.model}
                disabled={disabled}
                onChange={(event) => patchLan({ model: event.target.value })}
                fullWidth
              />
              <TextField
                size="small"
                label={copy.lanKeyEnv}
                value={value.lan.apiKeyEnv}
                disabled={disabled}
                helperText={copy.lanKeyHint}
                onChange={(event) => patchLan({ apiKeyEnv: event.target.value })}
                fullWidth
              />
            </Stack>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
              <TextField
                size="small"
                type="number"
                label={copy.timeoutText}
                value={value.lan.timeoutTextS}
                disabled={disabled}
                inputProps={{ min: 0.05, step: 0.1 }}
                onChange={(event) => patchLan({ timeoutTextS: Number(event.target.value) })}
                fullWidth
              />
              <TextField
                size="small"
                type="number"
                label={copy.timeoutImage}
                value={value.lan.timeoutImageS}
                disabled={disabled}
                inputProps={{ min: 0.5, step: 0.5 }}
                onChange={(event) => patchLan({ timeoutImageS: Number(event.target.value) })}
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
            <SectionTitle>{copy.multimodal}</SectionTitle>
            <FormControlLabel
              control={
                <Switch
                  checked={value.multimodal.enabled && value.multimodal.mode !== "text_only"}
                  disabled={disabled}
                  onChange={(event) =>
                    patchMultimodal({
                      enabled: event.target.checked,
                      mode: event.target.checked ? "crops_offline" : "text_only",
                    })
                  }
                />
              }
              label={copy.enableImages}
            />
            <FormControl size="small" fullWidth disabled={disabled}>
              <InputLabel>{copy.imageMode}</InputLabel>
              <Select
                value={value.multimodal.mode === "crops_offline" ? "crops_offline" : "text_only"}
                label={copy.imageMode}
                onChange={(event) =>
                  patchMultimodal({
                    mode: event.target.value === "crops_offline" ? "crops_offline" : "text_only",
                    enabled: event.target.value === "crops_offline",
                  })
                }
              >
                <MenuItem value="text_only">text_only</MenuItem>
                <MenuItem value="crops_offline">crops_offline</MenuItem>
                <MenuItem value="crops_live" disabled>
                  crops_live ({copy.locked})
                </MenuItem>
              </Select>
            </FormControl>
            <Typography variant="caption" color="warning.main">
              {copy.cropsLiveLocked}
            </Typography>
          </Stack>

          <Stack spacing={1}>
            <SectionTitle>{copy.usages}</SectionTitle>
            {JEV_GATE_USAGES.map((name) => (
              <Stack
                key={name}
                direction={{ xs: "column", sm: "row" }}
                spacing={1}
                alignItems={{ xs: "flex-start", sm: "center" }}
              >
                <FormControlLabel
                  sx={{ minWidth: 170 }}
                  control={
                    <Switch
                      checked={value.usages[name].enabled}
                      disabled={disabled}
                      onChange={(event) =>
                        onChange({
                          ...value,
                          usages: {
                            ...value.usages,
                            [name]: { ...value.usages[name], enabled: event.target.checked },
                          },
                        })
                      }
                    />
                  }
                  label={name}
                />
                <TextField
                  size="small"
                  type="number"
                  label={copy.usageTimeout}
                  value={value.usages[name].timeoutS}
                  disabled={disabled}
                  inputProps={{ min: 0.1, step: 0.5 }}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      usages: {
                        ...value.usages,
                        [name]: { ...value.usages[name], timeoutS: Number(event.target.value) },
                      },
                    })
                  }
                  sx={{ maxWidth: 220 }}
                />
              </Stack>
            ))}
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
