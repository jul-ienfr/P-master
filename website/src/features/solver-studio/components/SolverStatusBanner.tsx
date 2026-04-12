import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

export type SolverBackendState = "ready" | "loading" | "degraded" | "offline";

export interface SolverStatusMetric {
  label: string;
  value: string;
}

export interface SolverStatusBannerProps {
  state?: SolverBackendState;
  primaryLabel?: string;
  secondaryLabel?: string;
  note?: string;
  metrics?: SolverStatusMetric[];
}

const statePalette: Record<
  SolverBackendState,
  { label: string; background: string; border: string; color: string }
> = {
  ready: {
    label: "Ready",
    background: "rgba(104, 224, 185, 0.16)",
    border: "rgba(104, 224, 185, 0.35)",
    color: "#baf7de",
  },
  loading: {
    label: "Loading",
    background: "rgba(126, 183, 255, 0.14)",
    border: "rgba(126, 183, 255, 0.28)",
    color: "#d5e7ff",
  },
  degraded: {
    label: "Degraded",
    background: "rgba(255, 181, 92, 0.16)",
    border: "rgba(255, 181, 92, 0.34)",
    color: "#ffe0ba",
  },
  offline: {
    label: "Offline",
    background: "rgba(255, 132, 116, 0.16)",
    border: "rgba(255, 132, 116, 0.3)",
    color: "#ffd2c9",
  },
};

export function SolverStatusBanner({
  state = "ready",
  primaryLabel = "Native Rust backend",
  secondaryLabel = "HTTP standby available",
  note = "The deterministic solver remains authoritative even when auxiliary services are unavailable.",
  metrics = [],
}: SolverStatusBannerProps) {
  const palette = statePalette[state];

  return (
    <Paper
      variant="outlined"
      sx={{
        borderRadius: 4,
        overflow: "hidden",
        borderColor: palette.border,
        background:
          "linear-gradient(135deg, rgba(12, 19, 31, 0.96), rgba(10, 17, 28, 0.88) 55%, rgba(16, 31, 46, 0.9))",
        boxShadow: "0 24px 60px rgba(0, 0, 0, 0.28)",
      }}
    >
      <Stack
        direction={{ xs: "column", lg: "row" }}
        spacing={0}
        divider={
          <Divider
            flexItem
            orientation="vertical"
            sx={{ borderColor: "rgba(160, 186, 220, 0.12)", display: { xs: "none", lg: "block" } }}
          />
        }
      >
        <Box sx={{ flex: 1.35, p: { xs: 2.25, md: 2.5 }, display: "grid", gap: 1.25 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Chip
              label={palette.label}
              size="small"
              sx={{
                height: 28,
                fontWeight: 700,
                backgroundColor: palette.background,
                border: `1px solid ${palette.border}`,
                color: palette.color,
              }}
            />
            <Typography variant="overline" sx={{ letterSpacing: "0.18em", color: "#8fa8cc" }}>
              Solver pipeline
            </Typography>
          </Stack>

          <Box>
            <Typography variant="h5" sx={{ mb: 0.5 }}>
              {primaryLabel}
            </Typography>
            <Typography variant="body1" sx={{ color: "#dbe8fa" }}>
              {secondaryLabel}
            </Typography>
          </Box>

          <Typography variant="body2" sx={{ color: "#95a8c8", maxWidth: "70ch" }}>
            {note}
          </Typography>
        </Box>

        <Box
          sx={{
            flex: 1,
            p: { xs: 2.25, md: 2.5 },
            display: "grid",
            gap: 1,
            alignContent: "center",
            background:
              "linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0.01))",
          }}
        >
          {metrics.length > 0 ? (
            metrics.map((metric) => (
              <Stack
                key={metric.label}
                direction="row"
                alignItems="center"
                justifyContent="space-between"
                sx={{
                  py: 0.75,
                  borderBottom: "1px solid rgba(160, 186, 220, 0.1)",
                  "&:last-of-type": { borderBottom: 0, pb: 0 },
                }}
              >
                <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
                  {metric.label}
                </Typography>
                <Typography variant="subtitle2" sx={{ color: "#ecf4ff" }}>
                  {metric.value}
                </Typography>
              </Stack>
            ))
          ) : (
            <Typography variant="body2" sx={{ color: "#95a8c8" }}>
              No backend metrics attached yet.
            </Typography>
          )}
        </Box>
      </Stack>
    </Paper>
  );
}
