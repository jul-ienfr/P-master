import React from "react";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { LlmProviderStatus } from "../types";

export interface LlmProviderStatusChipProps {
  status: LlmProviderStatus;
  compact?: boolean;
}

function getChipColor(status: LlmProviderStatus): "default" | "success" | "warning" | "error" | "info" {
  switch (status.state) {
    case "ready":
      return "success";
    case "degraded":
      return "warning";
    case "error":
      return "error";
    case "disabled":
      return "default";
    case "unknown":
    default:
      return "info";
  }
}

export function LlmProviderStatusChip({ status, compact = false }: LlmProviderStatusChipProps) {
  return (
    <Stack spacing={compact ? 0.5 : 1} direction="row" alignItems="center" flexWrap="wrap">
      <Chip
        size={compact ? "small" : "medium"}
        color={getChipColor(status)}
        label={status.state}
        variant={status.healthy ? "filled" : "outlined"}
      />
      {!compact && (
        <Typography variant="body2" color="text.secondary">
          {status.reason}
        </Typography>
      )}
    </Stack>
  );
}

