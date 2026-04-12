import React from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import Grid from "@mui/material/Grid";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { createDefaultLlmConfig, getLlmPrivacyLabel, getLlmProviderLabel } from "../config";
import { LlmConfig, LlmProviderStatus, LlmRole, LlmScope } from "../types";
import { LlmProviderStatusChip } from "./LlmProviderStatusChip";

export interface LlmSettingsPanelProps {
  value: LlmConfig;
  onChange: (next: LlmConfig) => void;
  status?: LlmProviderStatus;
  disabled?: boolean;
}

const ROLE_LABELS: Record<LlmRole, string> = {
  analysis: "Analyse",
  operator_assistance: "Assistance opérateur",
  strategy_coach: "Coach stratégique",
  replay_review: "Revue replay",
};

const SCOPE_LABELS: Record<LlmScope, string> = {
  spot: "Spot",
  decision: "Décision",
  replay: "Relecture",
  runtime: "Exécution locale",
  ocr: "OCR",
  settings: "Réglages",
  fallback: "Secours",
};

function toggleMapEntry<T extends string>(
  input: Record<T, boolean>,
  key: T,
  nextValue: boolean
): Record<T, boolean> {
  return { ...input, [key]: nextValue };
}

export function LlmSettingsPanel({
  value,
  onChange,
  status,
  disabled = false,
}: LlmSettingsPanelProps) {
  const normalized = createDefaultLlmConfig(value);

  return (
    <Card variant="outlined" sx={{ borderRadius: 4, borderColor: "rgba(255,255,255,0.08)" }}>
      <CardContent>
        <Stack spacing={2.5}>
          <Stack spacing={1}>
            <Typography variant="overline" color="text.secondary">
              Réglages LLM
            </Typography>
            <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" flexWrap="wrap">
               <Typography variant="h6">Copilote optionnel</Typography>
              <FormControlLabel
                control={
                  <Switch
                    checked={normalized.enabled}
                    disabled={disabled}
                    onChange={(_, checked) =>
                      onChange({
                        ...normalized,
                        enabled: checked,
                        providerMode: checked
                          ? normalized.providerMode === "disabled"
                            ? "openai_compatible_remote"
                            : normalized.providerMode
                          : "disabled",
                      })
                    }
                  />
                }
                label="Activé"
              />
            </Stack>
            <Typography variant="body2" color="text.secondary">
              Désactivé par défaut. Le solver et le cockpit doivent continuer à fonctionner même si ce panneau n'est jamais configuré.
            </Typography>
          </Stack>

          <Divider />

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth size="small" disabled={disabled || !normalized.enabled}>
                <InputLabel id="llm-provider-mode-label">Mode fournisseur</InputLabel>
                <Select
                  labelId="llm-provider-mode-label"
                  label="Mode fournisseur"
                  value={normalized.providerMode}
                  onChange={(event) => {
                    const nextProviderMode = event.target.value as LlmConfig["providerMode"];
                    onChange({
                      ...normalized,
                      providerMode: nextProviderMode,
                      enabled: nextProviderMode === "disabled" ? false : true,
                    });
                  }}
                >
                  <MenuItem value="disabled">Désactivé</MenuItem>
                  <MenuItem value="openai_compatible_local">OpenAI-compatible local</MenuItem>
                  <MenuItem value="openai_compatible_remote">OpenAI-compatible distant</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth size="small" disabled={disabled || !normalized.enabled}>
                <InputLabel id="llm-privacy-mode-label">Mode de confidentialité</InputLabel>
                <Select
                  labelId="llm-privacy-mode-label"
                  label="Mode de confidentialité"
                  value={normalized.privacyMode}
                  onChange={(event) =>
                    onChange({
                      ...normalized,
                      privacyMode: event.target.value as LlmConfig["privacyMode"],
                    })
                  }
                >
                  <MenuItem value="strict_local">Strict local</MenuItem>
                  <MenuItem value="redacted_remote">Distant anonymisé</MenuItem>
                  <MenuItem value="full_remote">Distant complet</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                size="small"
                disabled={disabled || !normalized.enabled}
                label="URL de base"
                value={normalized.baseUrl}
                onChange={(event) => onChange({ ...normalized, baseUrl: event.target.value })}
                helperText="Endpoint compatible OpenAI, par exemple https://api.openai.com/v1 ou un proxy local."
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                size="small"
                disabled={disabled || !normalized.enabled}
                label="Modèle"
                value={normalized.model}
                onChange={(event) => onChange({ ...normalized, model: event.target.value })}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                size="small"
                disabled={disabled || !normalized.enabled}
                label="Référence de clé API"
                value={normalized.apiKeyRef}
                onChange={(event) => onChange({ ...normalized, apiKeyRef: event.target.value })}
                helperText="Référence abstraite résolue par le shell hôte ou un stockage sécurisé."
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <Typography gutterBottom>Température</Typography>
              <Slider
                disabled={disabled || !normalized.enabled}
                value={normalized.temperature}
                min={0}
                max={1}
                step={0.05}
                onChange={(_, nextValue) =>
                  onChange({ ...normalized, temperature: Array.isArray(nextValue) ? nextValue[0] : nextValue })
                }
                valueLabelDisplay="auto"
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                size="small"
                type="number"
                disabled={disabled || !normalized.enabled}
                label="Tokens de sortie max"
                value={normalized.maxOutputTokens}
                onChange={(event) =>
                  onChange({
                    ...normalized,
                    maxOutputTokens: Math.max(1, Number(event.target.value) || normalized.maxOutputTokens),
                  })
                }
              />
            </Grid>
          </Grid>

          <Divider />

          <FormGroup>
            <Typography variant="subtitle2">Rôles</Typography>
            <Grid container spacing={1}>
              {(Object.keys(ROLE_LABELS) as LlmRole[]).map((role) => (
                <Grid item xs={12} sm={6} key={role}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={normalized.rolesEnabled[role]}
                        disabled={disabled || !normalized.enabled}
                        onChange={(_, checked) =>
                          onChange({
                            ...normalized,
                            rolesEnabled: toggleMapEntry(normalized.rolesEnabled, role, checked),
                          })
                        }
                      />
                    }
                    label={ROLE_LABELS[role]}
                  />
                </Grid>
              ))}
            </Grid>
          </FormGroup>

          <FormGroup>
            <Typography variant="subtitle2">Périmètres de contexte</Typography>
            <Grid container spacing={1}>
              {(Object.keys(SCOPE_LABELS) as LlmScope[]).map((scope) => (
                <Grid item xs={12} sm={6} key={scope}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={normalized.contextScopesEnabled[scope]}
                        disabled={disabled || !normalized.enabled}
                        onChange={(_, checked) =>
                          onChange({
                            ...normalized,
                            contextScopesEnabled: toggleMapEntry(normalized.contextScopesEnabled, scope, checked),
                          })
                        }
                      />
                    }
                    label={SCOPE_LABELS[scope]}
                  />
                </Grid>
              ))}
            </Grid>
          </FormGroup>

          <Box sx={{ p: 2, borderRadius: 3, bgcolor: "rgba(255,255,255,0.03)" }}>
            <Stack spacing={0.75}>
              <Typography variant="subtitle2">Statut actuel</Typography>
              <Typography variant="body2" color="text.secondary">
                Fournisseur : {getLlmProviderLabel(normalized.providerMode)} · Confidentialité : {getLlmPrivacyLabel(normalized.privacyMode)}
              </Typography>
              {status ? <LlmProviderStatusChip status={status} /> : null}
            </Stack>
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}
