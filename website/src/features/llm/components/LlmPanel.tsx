import React, { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import FormControl from "@mui/material/FormControl";
import Grid from "@mui/material/Grid";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { createDefaultLlmConfig, getLlmTaskScopes } from "../config";
import { LlmAssistResponse, LlmAssistTask, LlmConfig, LlmProviderStatus } from "../types";
import { LlmProviderStatusChip } from "./LlmProviderStatusChip";

export interface LlmPanelProps {
  config: LlmConfig;
  status: LlmProviderStatus;
  value?: LlmAssistTask;
  response?: LlmAssistResponse | null;
  loading?: boolean;
  disabled?: boolean;
  onChange?: (task: LlmAssistTask) => void;
  onRunTask?: (task: LlmAssistTask) => Promise<LlmAssistResponse | void> | LlmAssistResponse | void;
  title?: string;
}

const TASK_LABELS: Record<LlmAssistTask["kind"], string> = {
  spot_explain: "Explication du spot",
  line_compare: "Comparaison de lines",
  decision_rationale: "Rationnel de décision",
  ocr_diagnostic: "Diagnostic OCR",
  fallback_diagnostic: "Diagnostic de secours",
  session_summary: "Résumé de session",
  strategy_review: "Revue stratégique",
  replay_coach: "Coach replay",
};

const DEFAULT_TASK: LlmAssistTask = {
  kind: "spot_explain",
  title: "Expliquer le spot courant",
  instruction: "",
  focusScopes: getLlmTaskScopes("spot_explain"),
};

function toTask(value?: LlmAssistTask): LlmAssistTask {
  if (!value) {
    return DEFAULT_TASK;
  }

  return {
    ...DEFAULT_TASK,
    ...value,
    focusScopes: value.focusScopes && value.focusScopes.length > 0 ? value.focusScopes : getLlmTaskScopes(value.kind),
  };
}

export function LlmPanel({
  config,
  status,
  value,
  response,
  loading = false,
  disabled = false,
  onChange,
  onRunTask,
  title = "Copilote",
}: LlmPanelProps) {
  const normalizedConfig = createDefaultLlmConfig(config);
  const [localTask, setLocalTask] = useState<LlmAssistTask>(toTask(value));

  const task = value ?? localTask;

  useEffect(() => {
    if (value) {
      setLocalTask(toTask(value));
    }
  }, [value]);

  const taskOptions = useMemo(() => Object.keys(TASK_LABELS) as LlmAssistTask["kind"][], []);

  const updateTask = (next: LlmAssistTask) => {
    if (onChange) {
      onChange(next);
    } else {
      setLocalTask(next);
    }
  };

  const runTask = async () => {
    if (!onRunTask) {
      return;
    }

    await onRunTask(task);
  };

  return (
    <Card variant="outlined" sx={{ borderRadius: 4, borderColor: "rgba(255,255,255,0.08)" }}>
      <CardContent>
        <Stack spacing={2.5}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap" spacing={1}>
            <Box>
              <Typography variant="overline" color="text.secondary">
                Panneau LLM
              </Typography>
              <Typography variant="h6">{title}</Typography>
            </Box>
            <LlmProviderStatusChip status={status} compact />
          </Stack>

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth size="small" disabled={disabled || !normalizedConfig.enabled}>
                <InputLabel id="llm-task-kind-label">Tâche</InputLabel>
                <Select
                  labelId="llm-task-kind-label"
                  label="Tâche"
                  value={task.kind}
                  onChange={(event) => {
                    const kind = event.target.value as LlmAssistTask["kind"];
                    updateTask({
                      ...task,
                      kind,
                      focusScopes: getLlmTaskScopes(kind),
                    });
                  }}
                >
                  {taskOptions.map((kind) => (
                    <MenuItem key={kind} value={kind}>
                      {TASK_LABELS[kind]}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                size="small"
                disabled={disabled || !normalizedConfig.enabled}
                label="Titre"
                value={task.title ?? ""}
                onChange={(event) => updateTask({ ...task, title: event.target.value })}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                multiline
                minRows={3}
                size="small"
                disabled={disabled || !normalizedConfig.enabled}
                label="Instruction"
                value={task.instruction ?? ""}
                onChange={(event) => updateTask({ ...task, instruction: event.target.value })}
                helperText="Utilise ce champ pour guider le copilote sans le coupler au chemin solver."
              />
            </Grid>
          </Grid>

          <Divider />

          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" justifyContent="space-between">
            <Typography variant="body2" color="text.secondary">
              Si le fournisseur est désactivé, absent ou bloqué, le panneau bascule vers une réponse locale sûre.
            </Typography>
            <Button
              variant="contained"
              onClick={runTask}
              disabled={disabled || loading || !normalizedConfig.enabled || !onRunTask}
            >
              {loading ? "Exécution..." : "Lancer le copilote"}
            </Button>
          </Stack>

          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, bgcolor: "rgba(255,255,255,0.02)" }}>
            <Stack spacing={1}>
              <Typography variant="subtitle2">Dernière réponse</Typography>
              {response ? (
                <>
                  <Typography variant="body2">{response.summary}</Typography>
                  {response.recommendations.length > 0 ? (
                    <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                      {response.recommendations.map((item, index) => (
                        <li key={`${index}-${item}`}>
                          <Typography variant="body2">{item}</Typography>
                        </li>
                      ))}
                    </Box>
                  ) : null}
                  {response.warnings.length > 0 ? (
                    <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                      {response.warnings.map((item, index) => (
                        <li key={`${index}-${item}`}>
                          <Typography variant="body2" color="warning.main">
                            {item}
                          </Typography>
                        </li>
                      ))}
                    </Box>
                  ) : null}
                  <Typography variant="caption" color="text.secondary">
                    Confiance : {Math.round(response.confidence * 100)}% · Latence : {response.latencyMs} ms
                  </Typography>
                </>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  Aucune réponse pour l'instant. Lance une tâche pour remplir la sortie du copilote.
                </Typography>
              )}
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, bgcolor: "rgba(255,255,255,0.02)" }}>
            <Stack spacing={0.75}>
              <Typography variant="subtitle2">Mode de secours sûr</Typography>
              <Typography variant="body2" color="text.secondary">
                {status.state === "disabled"
                  ? "Le LLM est désactivé. Le shell doit garder le solver et le cockpit pleinement fonctionnels."
                  : `Statut du fournisseur : ${status.state}. Le chemin de secours reste disponible pour le diagnostic.`}
              </Typography>
            </Stack>
          </Paper>
        </Stack>
      </CardContent>
    </Card>
  );
}
