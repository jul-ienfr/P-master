import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import type { ConfigLabOcrMode } from "../../../lib/configLab";
import type { ConfigLabOcrStatus } from "../../../lib/configLab";
import { getOcrSettingsCopy } from "../../../lib/workstationI18n";

export interface OcrSettingsPanelProps {
  locale?: "en" | "fr";
  enabledEngines: string[];
  mode: ConfigLabOcrMode;
  parallel: boolean;
  useGpu: boolean;
  status?: ConfigLabOcrStatus | null;
  onToggleEngine: (engine: string) => void;
  onMoveEngine: (engine: string, direction: "up" | "down") => void;
  onChangeMode: (mode: ConfigLabOcrMode) => void;
  onToggleParallel: (value: boolean) => void;
  onToggleUseGpu: (value: boolean) => void;
  onReset?: () => void;
}

const ENGINES = ["doctr", "tesseract", "easyocr"] as const;

export function OcrSettingsPanel({
  locale = "en",
  enabledEngines,
  mode,
  parallel,
  useGpu,
  status,
  onToggleEngine,
  onMoveEngine,
  onChangeMode,
  onToggleParallel,
  onToggleUseGpu,
  onReset,
}: OcrSettingsPanelProps) {
  const copy = getOcrSettingsCopy(locale);

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
              <Chip label={`${enabledEngines.length} ${copy.active}`} variant="outlined" color="info" />
              <Chip label={`${status?.loadedEngines.length ?? 0} ${copy.available}`} variant="outlined" color="success" />
              <Chip label={`${Object.keys(status?.unavailableEngines ?? {}).length} ${copy.unavailable}`} variant="outlined" color="warning" />
              <Button variant="outlined" onClick={onReset}>
                {copy.reset}
              </Button>
            </Stack>
          </Stack>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {ENGINES.map((engine) => {
              const active = enabledEngines.includes(engine);
              return (
                <Chip
                  key={engine}
                  label={status?.unavailableEngines?.[engine] ? `${engine} unavailable` : engine}
                  color={status?.unavailableEngines?.[engine] ? "warning" : active ? "primary" : "default"}
                  variant={active ? "filled" : "outlined"}
                  onClick={() => onToggleEngine(engine)}
                />
              );
            })}
          </Stack>

          {enabledEngines.length > 0 ? (
            <Stack spacing={1}>
              <Typography variant="caption" sx={{ color: "text.secondary", textTransform: "uppercase", letterSpacing: 1 }}>
                {copy.priority}
              </Typography>
              {enabledEngines.map((engine, index) => (
                <Stack key={engine} direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                  <Chip label={`${index + 1}. ${engine}`} color="primary" variant="outlined" />
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={index === 0}
                    onClick={() => onMoveEngine(engine, "up")}
                  >
                    {copy.up}
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={index === enabledEngines.length - 1}
                    onClick={() => onMoveEngine(engine, "down")}
                  >
                    {copy.down}
                  </Button>
                </Stack>
              ))}
            </Stack>
          ) : null}

          {status && Object.keys(status.unavailableEngines).length > 0 ? (
            <Stack spacing={0.5}>
              {Object.entries(status.unavailableEngines).map(([engine, reason]) => (
                <Typography key={engine} variant="caption" color="warning.main">
                  {engine}: {reason}
                </Typography>
              ))}
            </Stack>
          ) : null}

          <TextField
            select
            label={copy.mode}
            value={mode}
            onChange={(event) => onChangeMode(event.target.value as ConfigLabOcrMode)}
            size="small"
          >
            <MenuItem value="priority">priority</MenuItem>
            <MenuItem value="fallback">fallback</MenuItem>
            <MenuItem value="consensus_amounts">consensus_amounts</MenuItem>
          </TextField>

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
            <FormControlLabel
              control={<Switch checked={parallel} onChange={(event) => onToggleParallel(event.target.checked)} />}
              label={copy.parallel}
            />
            <FormControlLabel
              control={<Switch checked={useGpu} onChange={(event) => onToggleUseGpu(event.target.checked)} />}
              label={copy.useGpu}
            />
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
