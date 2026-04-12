import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  FormControlLabel,
  Stack,
  Switch,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { getRuntimeControlsCopy } from "../../../lib/workstationI18n";

export type RuntimeReadinessState = "ready" | "degraded" | "offline" | "checking";
export type PrivacyMode = "strict_local" | "redacted_remote" | "full_remote";

export interface RuntimeControlsPanelProps {
  locale?: "en" | "fr";
  runtimeState: RuntimeReadinessState;
  runtimeLabel?: string;
  backendLabel?: string;
  llmEnabled: boolean;
  privacyMode: PrivacyMode;
  benchmarkProfile?: string;
  benchmarkProfiles?: readonly string[];
  benchmarkEnabled?: boolean;
  latencyLabel?: string;
  cacheLabel?: string;
  onToggleLlm: (enabled: boolean) => void;
  onChangePrivacyMode: (mode: PrivacyMode) => void;
  onChangeBenchmarkProfile?: (profile: string) => void;
  onRunDiagnostics?: () => void;
  onRunBenchmarks?: () => void;
  onRefreshRuntime?: () => void;
}

const runtimeTone: Record<RuntimeReadinessState, "success" | "warning" | "error" | "info"> = {
  ready: "success",
  degraded: "warning",
  offline: "error",
  checking: "info",
};

function runtimeLabelFor(state: RuntimeReadinessState, locale: "en" | "fr") {
  switch (state) {
    case "ready":
      return locale === "fr" ? "Pret" : "Ready";
    case "degraded":
      return locale === "fr" ? "Degrade" : "Degraded";
    case "offline":
      return locale === "fr" ? "Hors ligne" : "Offline";
    case "checking":
      return locale === "fr" ? "Verification" : "Checking";
    default:
      return locale === "fr" ? "Inconnu" : "Unknown";
  }
}

export function RuntimeControlsPanel({
  locale = "en",
  runtimeState,
  runtimeLabel = "Local engine",
  backendLabel = "Native bridge",
  llmEnabled,
  privacyMode,
  benchmarkProfile,
  benchmarkProfiles = ["fast", "balanced", "deep"],
  benchmarkEnabled = true,
  latencyLabel,
  cacheLabel,
  onToggleLlm,
  onChangePrivacyMode,
  onChangeBenchmarkProfile,
  onRunDiagnostics,
  onRunBenchmarks,
  onRefreshRuntime,
}: RuntimeControlsPanelProps) {
  const copy = getRuntimeControlsCopy(locale);

  const panelFill = (mode: "light" | "dark") =>
    mode === "dark" ? "linear-gradient(180deg, rgba(10,20,35,0.98) 0%, rgba(18,29,45,0.95) 100%)" : "linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(245,247,250,0.98) 100%)";

  const cardTint = (mode: "light" | "dark") => (mode === "dark" ? 0.08 : 0.03);

  return (
    <Card
      elevation={0}
      sx={(theme) => ({
        borderRadius: 4,
        overflow: "hidden",
        border: 1,
        borderColor: "divider",
        background: panelFill(theme.palette.mode),
        color: theme.palette.text.primary,
        boxShadow: `0 20px 64px ${alpha(
          theme.palette.common.black,
          theme.palette.mode === "dark" ? 0.18 : 0.08
        )}`,
      })}
    >
      <CardContent sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} justifyContent="space-between">
            <Box>
              <Typography
                variant="overline"
                sx={(theme) => ({
                  letterSpacing: 1.8,
                  color: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.7 : 0.62),
                })}
              >
                {copy.kicker}
              </Typography>
              <Typography variant="h5" sx={{ fontWeight: 800, letterSpacing: -0.4 }}>
                {copy.title}
              </Typography>
              <Typography
                variant="body2"
                sx={(theme) => ({
                  mt: 0.5,
                  color: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.7 : 0.66),
                  maxWidth: 760,
                })}
              >
                {copy.subtitle}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} flexWrap="wrap" justifyContent={{ xs: "flex-start", sm: "flex-end" }}>
              <Chip label={runtimeLabelFor(runtimeState, locale)} color={runtimeTone[runtimeState]} />
              <Chip
                label={backendLabel}
                variant="outlined"
                sx={(theme) => ({
                  color: "text.primary",
                  borderColor: alpha(theme.palette.text.primary, 0.22),
                })}
              />
            </Stack>
          </Stack>

          <Divider sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.12) })} />

          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
            <Card
              variant="outlined"
              sx={(theme) => ({
                flex: 1,
                borderColor: alpha(theme.palette.text.primary, 0.12),
                bgcolor: alpha(theme.palette.text.primary, cardTint(theme.palette.mode)),
              })}
            >
              <CardContent>
                <Stack spacing={1.5}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                    {copy.runtimeState}
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={(theme) => ({
                      color: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.74 : 0.66),
                    })}
                  >
                    {runtimeLabel}
                  </Typography>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {latencyLabel ? <Chip size="small" label={latencyLabel} /> : null}
                    {cacheLabel ? <Chip size="small" label={cacheLabel} /> : null}
                  </Stack>
                  <Stack direction="row" spacing={1}>
                    <Button
                      variant="outlined"
                      onClick={onRefreshRuntime}
                      sx={(theme) => ({
                        borderColor: alpha(theme.palette.text.primary, 0.2),
                        color: "text.primary",
                      })}
                    >
                      {copy.refresh}
                    </Button>
                    <Button
                      variant="outlined"
                      onClick={onRunDiagnostics}
                      sx={(theme) => ({
                        borderColor: alpha(theme.palette.text.primary, 0.2),
                        color: "text.primary",
                      })}
                    >
                      {copy.diagnostics}
                    </Button>
                  </Stack>
                </Stack>
              </CardContent>
            </Card>

            <Card
              variant="outlined"
              sx={(theme) => ({
                flex: 1,
                borderColor: alpha(theme.palette.text.primary, 0.12),
                bgcolor: alpha(theme.palette.text.primary, cardTint(theme.palette.mode)),
              })}
            >
              <CardContent>
                <Stack spacing={2}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                    {copy.copilot}
                  </Typography>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={llmEnabled}
                        onChange={(event) => onToggleLlm(event.target.checked)}
                        color="primary"
                      />
                    }
                    label={
                      <Stack>
                        <Typography variant="body2" sx={{ color: "text.primary" }}>
                          {copy.enableCopilot}
                        </Typography>
                        <Typography
                          variant="caption"
                          sx={(theme) => ({
                            color: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.68 : 0.6),
                          })}
                        >
                          {copy.copilotHint}
                        </Typography>
                      </Stack>
                    }
                  />

                  <ToggleButtonGroup
                    exclusive
                    value={privacyMode}
                    onChange={(_, value) => {
                      if (value) onChangePrivacyMode(value);
                    }}
                    fullWidth
                    size="small"
                    sx={(theme) => ({
                      "& .MuiToggleButton-root": {
                        color: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.82 : 0.74),
                        borderColor: alpha(theme.palette.text.primary, 0.14),
                      },
                      "& .Mui-selected": {
                        color: `${theme.palette.text.primary} !important`,
                        bgcolor: alpha(theme.palette.primary.main, theme.palette.mode === "dark" ? 0.22 : 0.14),
                      },
                    })}
                  >
                    <ToggleButton value="strict_local">{copy.strictLocal}</ToggleButton>
                    <ToggleButton value="redacted_remote">{copy.redactedRemote}</ToggleButton>
                    <ToggleButton value="full_remote">{copy.fullRemote}</ToggleButton>
                  </ToggleButtonGroup>
                </Stack>
              </CardContent>
            </Card>
          </Stack>

          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
            <Card
              variant="outlined"
              sx={(theme) => ({
                flex: 1,
                borderColor: alpha(theme.palette.text.primary, 0.12),
                bgcolor: alpha(theme.palette.text.primary, cardTint(theme.palette.mode)),
              })}
            >
              <CardContent>
                <Stack spacing={2}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                    {copy.benchmarkProfile}
                  </Typography>
                  <ToggleButtonGroup
                    exclusive
                    fullWidth
                    size="small"
                    value={benchmarkProfile ?? ""}
                    onChange={(_, value) => {
                      if (value && onChangeBenchmarkProfile) onChangeBenchmarkProfile(value);
                    }}
                    disabled={!benchmarkEnabled}
                    sx={(theme) => ({
                      "& .MuiToggleButton-root": {
                        color: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.82 : 0.74),
                        borderColor: alpha(theme.palette.text.primary, 0.14),
                      },
                      "& .Mui-selected": {
                        color: `${theme.palette.text.primary} !important`,
                        bgcolor: alpha(theme.palette.success.main, theme.palette.mode === "dark" ? 0.2 : 0.14),
                      },
                    })}
                  >
                    {benchmarkProfiles.map((profile) => (
                      <ToggleButton key={profile} value={profile}>
                        {profile}
                      </ToggleButton>
                    ))}
                  </ToggleButtonGroup>
                  <Stack direction="row" spacing={1}>
                    <Button variant="contained" onClick={onRunBenchmarks} disabled={!benchmarkEnabled}>
                      {copy.runLab}
                    </Button>
                  </Stack>
                </Stack>
              </CardContent>
            </Card>

            <Card
              variant="outlined"
              sx={(theme) => ({
                flex: 1,
                borderColor: alpha(theme.palette.text.primary, 0.12),
                bgcolor: alpha(theme.palette.text.primary, cardTint(theme.palette.mode)),
              })}
            >
              <CardContent>
                <Stack spacing={1.5}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                    {copy.readiness}
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={(theme) => ({
                      color: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.74 : 0.66),
                    })}
                  >
                    {copy.readinessHelp}
                  </Typography>
                  <Box
                    sx={(theme) => ({
                      height: 8,
                      borderRadius: 999,
                      bgcolor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.14 : 0.08),
                      overflow: "hidden",
                    })}
                  >
                    <Box
                      sx={{
                        height: "100%",
                        width: runtimeState === "ready" ? "100%" : runtimeState === "degraded" ? "66%" : runtimeState === "checking" ? "42%" : "18%",
                        bgcolor:
                          runtimeState === "ready"
                            ? "#59C173"
                            : runtimeState === "degraded"
                              ? "#F5A623"
                              : runtimeState === "checking"
                                ? "#5B8DEF"
                                : "#FF6B6B",
                      }}
                    />
                  </Box>
                </Stack>
              </CardContent>
            </Card>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
