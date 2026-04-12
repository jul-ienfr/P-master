import { useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import type { ConfigLabOcrMode } from "../../../lib/configLab";
import { getOcrProbeCopy } from "../../../lib/workstationI18n";

export interface OcrProbeResult {
  success: boolean;
  field: string;
  result: unknown;
  metadata: Record<string, unknown>;
  message?: string;
}

export interface OcrProbePanelProps {
  locale?: "en" | "fr";
  enabledEngines: string[];
  mode: ConfigLabOcrMode;
  parallel: boolean;
  onRunProbe: (file: File, field: "text" | "amount") => Promise<OcrProbeResult>;
}

export function OcrProbePanel({
  locale = "en",
  enabledEngines,
  mode,
  parallel,
  onRunProbe,
}: OcrProbePanelProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [field, setField] = useState<"text" | "amount">("amount");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<OcrProbeResult | null>(null);

  const copy = getOcrProbeCopy(locale);

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
            ? "linear-gradient(180deg, rgba(15,21,31,0.96) 0%, rgba(12,16,24,0.92) 100%)"
            : "linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(247,250,252,0.98) 100%)",
        boxShadow: `0 18px 60px ${alpha(theme.palette.common.black, theme.palette.mode === "dark" ? 0.22 : 0.08)}`,
      })}
    >
      <CardContent sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="overline" sx={{ letterSpacing: 1.8, color: "text.secondary" }}>
              {copy.kicker}
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 800, letterSpacing: -0.4 }}>
              {copy.title}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {copy.subtitle}
            </Typography>
          </Box>

          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip label={`${enabledEngines.length} ${copy.active}`} variant="outlined" color="info" />
            <Chip label={`${copy.modeLabel}: ${mode}`} variant="outlined" />
            <Chip label={`${copy.parallelLabel}: ${parallel ? "on" : "off"}`} variant="outlined" />
          </Stack>

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }}>
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              style={{ display: "none" }}
              onChange={(event) => {
                const nextFile = event.target.files?.[0] ?? null;
                setFile(nextFile);
                setResult(null);
              }}
            />
            <Button variant="outlined" onClick={() => inputRef.current?.click()}>
              {copy.choose}
            </Button>
            <Typography variant="body2" color="text.secondary">
              {file?.name ?? copy.noFile}
            </Typography>
            <TextField
              select
              label={copy.field}
              size="small"
              value={field}
              onChange={(event) => setField(event.target.value as "text" | "amount")}
              sx={{ minWidth: 160 }}
            >
              <MenuItem value="amount">amount</MenuItem>
              <MenuItem value="text">text</MenuItem>
            </TextField>
            <Button
              variant="contained"
              disabled={!file || running || enabledEngines.length === 0}
              onClick={async () => {
                if (!file) {
                  return;
                }
                setRunning(true);
                try {
                  setResult(await onRunProbe(file, field));
                } finally {
                  setRunning(false);
                }
              }}
            >
              {running ? "..." : copy.run}
            </Button>
          </Stack>

          {result ? (
            <Stack spacing={1.25}>
              <Alert severity={result.success ? "success" : "error"}>
                {result.success
                  ? `${result.field}: ${String(result.result ?? "")}`
                  : result.message ?? copy.failed}
              </Alert>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                {Array.isArray(result.metadata.candidates)
                  ? result.metadata.candidates.map((candidate, index) => {
                      const row = candidate as Record<string, unknown>;
                      const engine = typeof row.engine === "string" ? row.engine : `engine-${index + 1}`;
                      const score = typeof row.score === "number" ? row.score.toFixed(2) : "0.00";
                      const value = typeof row.value === "number"
                        ? String(row.value)
                        : typeof row.text === "string"
                          ? row.text
                          : "n/a";
                      return <Chip key={`${engine}-${index}`} label={`${engine} · ${value} · score ${score}`} variant="outlined" />;
                    })
                  : null}
              </Stack>
            </Stack>
          ) : null}
        </Stack>
      </CardContent>
    </Card>
  );
}
