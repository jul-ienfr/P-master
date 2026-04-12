import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { DecisionSnapshot, SpotSnapshot } from "../../llm/types";
import {
  SolverStatusBanner,
  type SolverBackendState,
  type SolverStatusMetric,
} from "./SolverStatusBanner";
import { SpotMetadataCard } from "./SpotMetadataCard";
import { ActionMixCard } from "./ActionMixCard";

export interface StrategySummaryCardsProps {
  spot?: SpotSnapshot | null;
  decision?: DecisionSnapshot | null;
  backendState?: SolverBackendState;
  backendLabel?: string;
  fallbackLabel?: string;
  backendNote?: string;
  backendMetrics?: SolverStatusMetric[];
  title?: string;
  subtitle?: string;
}

export function StrategySummaryCards({
  spot,
  decision,
  backendState = "ready",
  backendLabel = "Native solver path active",
  fallbackLabel = "HTTP and local fallback remain isolated from the main action path",
  backendNote,
  backendMetrics = [],
  title = "Solver summary",
  subtitle = "Read the spot, backend health, and action mix in one compact premium strip.",
}: StrategySummaryCardsProps) {
  const inferredNote =
    backendNote ??
    (decision?.source === "http"
      ? "The current answer came from the HTTP bridge. Keep an eye on parity before trusting repeated use."
      : decision?.source === "fallback"
        ? "The deterministic fallback path answered this spot. Study the warnings before acting on the result."
        : "Native runtime remains the primary path and the summary below is built to make line quality legible at a glance.");

  return (
    <Stack spacing={2}>
      <Stack spacing={0.5}>
        <Typography variant="overline" sx={{ color: "#8fa8cc", letterSpacing: "0.16em" }}>
          Solver studio
        </Typography>
        <Typography variant="h5">{title}</Typography>
        <Typography variant="body2" sx={{ color: "#95a8c8", maxWidth: "68ch" }}>
          {subtitle}
        </Typography>
      </Stack>

      <SolverStatusBanner
        state={backendState}
        primaryLabel={backendLabel}
        secondaryLabel={fallbackLabel}
        note={inferredNote}
        metrics={backendMetrics}
      />

      <Grid container spacing={2}>
        <Grid item xs={12} xl={5}>
          <SpotMetadataCard spot={spot} />
        </Grid>
        <Grid item xs={12} xl={7}>
          <ActionMixCard decision={decision} />
        </Grid>
      </Grid>
    </Stack>
  );
}
