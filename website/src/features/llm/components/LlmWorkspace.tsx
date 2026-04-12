import React from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { LlmAssistResponse, LlmAssistTask, LlmConfig } from "../types";
import { LlmFeatureProvider, useLlmFeature } from "../context";
import { LlmPanel } from "./LlmPanel";
import { LlmSettingsPanel } from "./LlmSettingsPanel";

export interface LlmWorkspaceProps {
  initialConfig?: Partial<LlmConfig>;
  initialTask?: LlmAssistTask;
  resolveApiKey?: (apiKeyRef: string) => Promise<string | null> | string | null;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  persistConfig?: (config: LlmConfig) => Promise<void> | void;
  runFallbackTask?: (task: LlmAssistTask, config: LlmConfig) => Promise<LlmAssistResponse | null> | LlmAssistResponse | null;
}

function LlmWorkspaceContent({ initialTask }: { initialTask?: LlmAssistTask }) {
  const { config, status, setConfig, lastResponse, lastTask, runTask } = useLlmFeature();
  const [task, setTask] = React.useState<LlmAssistTask | undefined>(initialTask);

  React.useEffect(() => {
    setTask(initialTask);
  }, [initialTask]);

  return (
    <Box>
      <Stack spacing={2} sx={{ mb: 2 }}>
        <Typography variant="h5">Copilote LLM</Typography>
        <Typography variant="body2" color="text.secondary">
          Optionnel, désactivé par défaut et maintenu hors du chemin déterministe du solver.
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {lastTask ? `Dernière tâche : ${lastTask.kind}` : "Aucune tâche lancée pour l'instant"}
        </Typography>
      </Stack>
      <Grid container spacing={2}>
        <Grid item xs={12} lg={5}>
          <LlmSettingsPanel value={config} onChange={setConfig} status={status} />
        </Grid>
        <Grid item xs={12} lg={7}>
          <LlmPanel
            config={config}
            status={status}
            value={task}
            response={lastResponse}
            onChange={setTask}
            onRunTask={async (nextTask) => {
              setTask(nextTask);
              const execution = await runTask(nextTask);
              return execution.response;
            }}
          />
        </Grid>
      </Grid>
    </Box>
  );
}

export function LlmWorkspace({
  initialConfig,
  initialTask,
  resolveApiKey,
  fetchImpl,
  timeoutMs,
  persistConfig,
  runFallbackTask,
}: LlmWorkspaceProps) {
  return (
    <LlmFeatureProvider
      initialConfig={initialConfig}
      resolveApiKey={resolveApiKey}
      fetchImpl={fetchImpl}
      timeoutMs={timeoutMs}
      persistConfig={persistConfig}
      runFallbackTask={runFallbackTask}
    >
      <LlmWorkspaceContent initialTask={initialTask} />
    </LlmFeatureProvider>
  );
}
