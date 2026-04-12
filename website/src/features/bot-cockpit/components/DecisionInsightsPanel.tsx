import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import type { ReactNode } from "react";
import type { CockpitHistoryViewMode } from "../types";

export interface DecisionInsightsPanelProps {
  locale?: "en" | "fr";
  explanation?: string;
  warningHistory?: string[];
  fallbackHistory?: string[];
  runtimeHistory?: string[];
  currentAction?: string;
  gateReason?: string;
  incidentHistory?: string[];
  actionHistory?: string[];
  historyView?: CockpitHistoryViewMode;
  availableHistoryViews?: CockpitHistoryViewMode[];
  onHistoryViewChange?: (mode: CockpitHistoryViewMode) => void;
}

function prettifyHistoryLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function HistorySection({
  title,
  emptyLabel,
  values,
  color,
  actions,
}: {
  title: string;
  emptyLabel: string;
  values: string[];
  color: "warning" | "info" | "error" | "primary";
  actions?: ReactNode;
}) {
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }} useFlexGap flexWrap="wrap">
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
          <Typography variant="subtitle2">{title}</Typography>
          {actions}
        </Stack>
        <Chip label={values.length} size="small" variant="outlined" />
      </Stack>
      {values.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {emptyLabel}
        </Typography>
      ) : (
        <Stack spacing={0.9}>
          {values.map((value, index) => (
            <Box
              key={`${value}-${index}`}
              sx={(theme) => ({
                borderRadius: 2.5,
                border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.05 : 0.025),
                px: 1.25,
                py: 1,
              })}
            >
              <Stack direction="row" spacing={1} alignItems="flex-start">
                <Chip label={index + 1} size="small" color={color} sx={{ minWidth: 32 }} />
                <Typography variant="body2" sx={{ pt: 0.25 }}>
                  {prettifyHistoryLabel(value)}
                </Typography>
              </Stack>
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}

export function DecisionInsightsPanel({
  locale = "en",
  explanation,
  warningHistory = [],
  fallbackHistory = [],
  runtimeHistory = [],
  currentAction,
  gateReason,
  incidentHistory = [],
  actionHistory = [],
  historyView = "combined",
  availableHistoryViews = ["combined"],
  onHistoryViewChange,
}: DecisionInsightsPanelProps) {
  const copy =
    locale === "fr"
      ? {
          title: "Explication de decision",
          subtitle: "Lecture humaine de la decision, des warnings et des fallbacks observes.",
          explanation: "Explication",
          warnings: "Historique warnings",
          fallbacks: "Historique fallbacks",
          runtimeHistory: "Historique runtime",
          noExplanation: "Aucune explication detaillee n’a ete fournie pour cette decision.",
          noWarnings: "Aucun warning memorise.",
          noFallbacks: "Aucun fallback memorise.",
          noRuntimeHistory: "Aucun historique runtime capture.",
          action: "Action courante",
          localHistory: "Historique local",
          noLocalHistory: "Aucun historique local capture.",
          gate: "Gate",
          incidents: "Historique incidents",
          noIncidents: "Aucun incident memorise.",
          historyRuntime: "Runtime",
          historyPersisted: "Persisté",
          historyCombined: "Combiné",
        }
      : {
          title: "Decision explanation",
          subtitle: "Human-readable decision context, warnings, and fallback history.",
          explanation: "Explanation",
          warnings: "Warning history",
          fallbacks: "Fallback history",
          runtimeHistory: "Runtime history",
          noExplanation: "No detailed explanation was attached to this decision.",
          noWarnings: "No warnings were recorded.",
          noFallbacks: "No fallbacks were recorded.",
          noRuntimeHistory: "No runtime history was captured.",
          action: "Current action",
          localHistory: "Local history",
          noLocalHistory: "No local history was captured.",
          gate: "Gate",
          incidents: "Incident history",
          noIncidents: "No incidents were recorded.",
          historyRuntime: "Runtime",
          historyPersisted: "Persisted",
          historyCombined: "Combined",
        };
  const historyViewLabels: Record<CockpitHistoryViewMode, string> = {
    runtime: copy.historyRuntime,
    persisted: copy.historyPersisted,
    combined: copy.historyCombined,
  };

  return (
    <Card
      variant="outlined"
      sx={(theme) => ({
        borderRadius: 5,
        overflow: "hidden",
        borderColor: alpha(theme.palette.text.primary, 0.08),
        background: theme.palette.background.paper,
        boxShadow:
          theme.palette.mode === "dark"
            ? "0 18px 44px rgba(0, 0, 0, 0.28)"
            : "0 10px 30px rgba(15, 23, 42, 0.06)",
      })}
    >
      <CardContent sx={{ p: { xs: 2.25, md: 2.75 } }}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="overline" color="text.secondary">
              Bot Cockpit
            </Typography>
            <Typography variant="h5">{copy.title}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {copy.subtitle}
            </Typography>
          </Box>

          <Box
            sx={(theme) => ({
              borderRadius: 3,
              border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
              background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.06 : 0.03),
              px: 1.75,
              py: 1.5,
            })}
          >
            <Stack spacing={1}>
              <Typography variant="caption" color="text.secondary">
                {copy.explanation}
              </Typography>
              {currentAction ? <Chip label={`${copy.action} · ${currentAction}`} size="small" color="primary" /> : null}
              {gateReason ? <Chip label={`${copy.gate} · ${gateReason}`} size="small" variant="outlined" /> : null}
              <Typography variant="body2">
                {explanation || copy.noExplanation}
              </Typography>
            </Stack>
          </Box>

          <Divider />

          <HistorySection
            title={copy.warnings}
            emptyLabel={copy.noWarnings}
            values={warningHistory}
            color="warning"
          />

          <HistorySection
            title={copy.fallbacks}
            emptyLabel={copy.noFallbacks}
            values={fallbackHistory}
            color="info"
          />

          {runtimeHistory.length > 0 ? (
            <HistorySection
              title={copy.runtimeHistory}
              emptyLabel={copy.noRuntimeHistory}
              values={runtimeHistory}
              color="primary"
            />
          ) : null}

          <HistorySection
            title={copy.localHistory}
            emptyLabel={copy.noLocalHistory}
            values={actionHistory}
            color="primary"
            actions={
              availableHistoryViews.length > 1 ? (
                <ToggleButtonGroup
                  size="small"
                  exclusive
                  value={historyView}
                  onChange={(_, value: CockpitHistoryViewMode | null) => {
                    if (value && onHistoryViewChange) {
                      onHistoryViewChange(value);
                    }
                  }}
                >
                  {availableHistoryViews.map((mode) => (
                    <ToggleButton key={mode} value={mode} sx={{ px: 1, py: 0.25, textTransform: "none" }}>
                      {historyViewLabels[mode]}
                    </ToggleButton>
                  ))}
                </ToggleButtonGroup>
              ) : null
            }
          />

          <HistorySection
            title={copy.incidents}
            emptyLabel={copy.noIncidents}
            values={incidentHistory}
            color="error"
          />
        </Stack>
      </CardContent>
    </Card>
  );
}

export default DecisionInsightsPanel;
