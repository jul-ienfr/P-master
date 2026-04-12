import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createLlmClient, LlmClient } from "./client";
import { createDefaultLlmConfig } from "./config";
import {
  createDefaultLlmProviderStatus,
  createDegradedLlmProviderStatus,
  createSafeLlmAssistResponse,
} from "./status";
import { LlmAssistExecution, LlmAssistResponse, LlmAssistTask, LlmConfig, LlmProviderStatus } from "./types";

interface LlmFeatureContextValue {
  config: LlmConfig;
  status: LlmProviderStatus;
  lastResponse: LlmAssistResponse | null;
  lastTask: LlmAssistTask | null;
  setConfig: React.Dispatch<React.SetStateAction<LlmConfig>>;
  runTask: (task: LlmAssistTask) => Promise<LlmAssistExecution>;
  client: LlmClient;
}

const LlmFeatureContext = createContext<LlmFeatureContextValue | null>(null);

export interface LlmFeatureProviderProps {
  children: React.ReactNode;
  initialConfig?: Partial<LlmConfig>;
  resolveApiKey?: (apiKeyRef: string) => Promise<string | null> | string | null;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  persistConfig?: (config: LlmConfig) => Promise<void> | void;
  runFallbackTask?: (task: LlmAssistTask, config: LlmConfig) => Promise<LlmAssistResponse | null> | LlmAssistResponse | null;
}

export function LlmFeatureProvider({
  children,
  initialConfig,
  resolveApiKey,
  fetchImpl,
  timeoutMs,
  persistConfig,
  runFallbackTask,
}: LlmFeatureProviderProps) {
  const [config, setConfig] = useState<LlmConfig>(createDefaultLlmConfig(initialConfig ?? {}));
  const [lastResponse, setLastResponse] = useState<LlmAssistResponse | null>(null);
  const [lastTask, setLastTask] = useState<LlmAssistTask | null>(null);
  const [status, setStatus] = useState<LlmProviderStatus>(() =>
    createDefaultLlmProviderStatus(initialConfig)
  );
  const hasMountedRef = useRef(false);

  const client = useMemo(
    () =>
      createLlmClient({
        config,
        resolveApiKey,
        fetchImpl,
        timeoutMs,
      }),
    [config, resolveApiKey, fetchImpl, timeoutMs]
  );

  useEffect(() => {
    setStatus(client.status ?? createDefaultLlmProviderStatus(config));
  }, [client.status, config]);

  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }

    if (!persistConfig) {
      return;
    }

    Promise.resolve(persistConfig(config)).catch((error) => {
      const reason = error instanceof Error ? error.message : "failed to persist LLM config";
      setStatus(createDegradedLlmProviderStatus(config, reason));
    });
  }, [config, persistConfig]);

  const value = useMemo<LlmFeatureContextValue>(() => {
    const runHostFallback = async (
      task: LlmAssistTask,
      nextStatus: LlmProviderStatus,
      reason: string
    ): Promise<LlmAssistExecution> => {
      if (runFallbackTask) {
        try {
          const fallbackResponse = await runFallbackTask(task, config);
          if (fallbackResponse) {
            return {
              status: nextStatus,
              response: fallbackResponse,
            };
          }
        } catch (error) {
          const fallbackReason = error instanceof Error ? error.message : "host fallback failed";
          return {
            status: createDegradedLlmProviderStatus(config, fallbackReason),
            response: createSafeLlmAssistResponse(task, fallbackReason, config),
          };
        }
      }

      return {
        status: nextStatus,
        response: createSafeLlmAssistResponse(task, reason, config),
      };
    };

    return {
      config,
      status,
      lastResponse,
      lastTask,
      setConfig,
      client,
      runTask: async (task: LlmAssistTask) => {
        setLastTask(task);
        let execution: LlmAssistExecution;

        if (!config.enabled || config.providerMode === "disabled") {
          execution = await runHostFallback(
            task,
            createDefaultLlmProviderStatus(config),
            "LLM is disabled"
          );
        } else {
          const taskDescription = client.describeTask(task);
          const clientExecution = await client.runTask(task);
          const shouldFallback =
            taskDescription.allowed &&
            (clientExecution.status.state === "degraded" || clientExecution.status.state === "error");

          execution = shouldFallback && runFallbackTask
            ? await runHostFallback(task, clientExecution.status, clientExecution.status.reason)
            : clientExecution;
        }

        setStatus(execution.status);
        setLastResponse(execution.response ?? createSafeLlmAssistResponse(task, "No response returned", config));
        return execution;
      },
    };
  }, [client, config, lastResponse, lastTask, runFallbackTask, status]);

  return <LlmFeatureContext.Provider value={value}>{children}</LlmFeatureContext.Provider>;
}

export function useLlmFeature(): LlmFeatureContextValue {
  const context = useContext(LlmFeatureContext);
  if (!context) {
    throw new Error("useLlmFeature must be used inside an LlmFeatureProvider");
  }

  return context;
}
