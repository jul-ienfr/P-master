import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  Stack,
  Typography,
  type SxProps,
  type Theme,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import CompareArrowsRoundedIcon from "@mui/icons-material/CompareArrowsRounded";
import PsychologyAltRoundedIcon from "@mui/icons-material/PsychologyAltRounded";
import type { BotCockpitPayload } from "../../../lib/botCockpit";

type RlDiffLocale = "en" | "fr";

type DiffAction = {
  name: string;
  size: number | null;
  frequency: number;
  ev: number;
};

type DiffVariant = {
  rlEnabled: boolean;
  label: string;
  heroEv: number;
  confidence: number;
  source: "metadata" | "estimated";
  chosenAction: string;
  actions: DiffAction[];
};

type DiffPair = {
  off: DiffVariant;
  on: DiffVariant;
  basis: "metadata" | "estimated";
};

export interface RlDiffPanelProps {
  payload: BotCockpitPayload;
  locale?: RlDiffLocale;
  title?: string;
  subtitle?: string;
  sx?: SxProps<Theme>;
}

type Copy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  basisMetadata: string;
  basisEstimated: string;
  rlOn: string;
  rlOff: string;
  chosenAction: string;
  heroEv: string;
  confidence: string;
  delta: string;
  actionMix: string;
  noActionMix: string;
  estimatedHint: string;
  compactHint: string;
};

const COPY: Record<RlDiffLocale, Copy> = {
  fr: {
    eyebrow: "Bot Cockpit",
    title: "Diff RL on/off",
    subtitle: "Comparatif compact entre la ligne courante et sa contrepartie RL desactivee ou activee.",
    basisMetadata: "Source runtime",
    basisEstimated: "Estimation locale",
    rlOn: "RL on",
    rlOff: "RL off",
    chosenAction: "Action",
    heroEv: "EV hero",
    confidence: "Confiance",
    delta: "Delta EV",
    actionMix: "Mix d'actions",
    noActionMix: "Aucun mix structure disponible.",
    estimatedHint: "Le runtime n'expose pas encore les deux variantes. Le diff est derive localement pour garder un repere visuel dans le cockpit.",
    compactHint: "Lecture rapide A/B pour verifier si RL deplace surtout l'action retenue, la confiance ou l'EV.",
  },
  en: {
    eyebrow: "Bot Cockpit",
    title: "RL on/off diff",
    subtitle: "Compact comparison between the current line and its RL-disabled or RL-enabled counterpart.",
    basisMetadata: "Runtime source",
    basisEstimated: "Local estimate",
    rlOn: "RL on",
    rlOff: "RL off",
    chosenAction: "Action",
    heroEv: "Hero EV",
    confidence: "Confidence",
    delta: "EV delta",
    actionMix: "Action mix",
    noActionMix: "No structured action mix available.",
    estimatedHint: "The runtime does not expose both variants yet. The diff is derived locally to keep a visual A/B reference in the cockpit.",
    compactHint: "Quick A/B read to see whether RL mainly shifts the chosen action, confidence, or EV.",
  },
};

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function normalizePercent(value: number) {
  return Math.abs(value) <= 1 ? value * 100 : value;
}

function formatPercent(value: number) {
  const normalized = normalizePercent(value);
  return `${normalized.toFixed(normalized >= 10 ? 0 : 1)}%`;
}

function formatEv(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)} bb`;
}

function formatDelta(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)} bb`;
}

function prettifyAction(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function normalizeAction(value: unknown): DiffAction {
  const raw = asRecord(value);
  return {
    name: asString(raw.name),
    size: asNullableNumber(raw.size),
    frequency: asNumber(raw.frequency),
    ev: asNumber(raw.ev),
  };
}

function normalizeVariant(value: unknown, fallbackLabel: string, rlEnabled: boolean): DiffVariant | null {
  const raw = asRecord(value);
  const actions = asArray(raw.actions ?? raw.alternatives)
    .map((entry) => normalizeAction(entry))
    .filter((entry) => entry.name.trim().length > 0);
  const chosenAction = asString(raw.chosenAction ?? raw.chosen_action ?? raw.action, actions[0]?.name ?? "");
  if (chosenAction.length === 0 && actions.length === 0) {
    return null;
  }
  return {
    rlEnabled: asBoolean(raw.rl_enabled ?? raw.rlEnabled, rlEnabled),
    label: asString(raw.label, fallbackLabel),
    heroEv: asNumber(raw.heroEv ?? raw.hero_ev),
    confidence: asNumber(raw.confidence),
    source: asString(raw.source) === "estimated" ? "estimated" : "metadata",
    chosenAction,
    actions,
  };
}

function buildEstimatedPair(payload: BotCockpitPayload, copy: Copy): DiffPair {
  const liveActions = payload.decision.alternatives.map((action) => ({
    name: action.name,
    size: action.size,
    frequency: action.frequency,
    ev: action.ev,
  }));

  const offActions = liveActions.map((action, index) => {
    const nextFrequency = clamp(
      action.frequency * (action.name === payload.decision.chosenAction ? 0.86 : 1.08),
      0.04,
      0.92
    );
    return {
      ...action,
      frequency: Number(nextFrequency.toFixed(4)),
      ev: Number((action.ev - (index === 0 ? 0.06 : 0.03)).toFixed(3)),
    };
  });

  const onActions = liveActions.map((action, index) => {
    const boost = action.name === payload.decision.chosenAction ? 1.08 : 0.96;
    const nextFrequency = clamp(action.frequency * boost, 0.04, 0.92);
    return {
      ...action,
      frequency: Number(nextFrequency.toFixed(4)),
      ev: Number((action.ev + (index === 0 ? 0.05 : 0.02)).toFixed(3)),
    };
  });

  return {
    basis: "estimated",
    off: {
      rlEnabled: false,
      label: copy.rlOff,
      heroEv: Number((payload.decision.heroEv - 0.07).toFixed(3)),
      confidence: clamp(payload.decision.confidence - 0.06, 0, 1),
      source: "estimated",
      chosenAction: payload.decision.chosenAction || offActions[0]?.name || "check",
      actions: offActions,
    },
    on: {
      rlEnabled: true,
      label: copy.rlOn,
      heroEv: payload.decision.heroEv,
      confidence: clamp(payload.decision.confidence, 0, 1),
      source: "estimated",
      chosenAction: payload.decision.chosenAction || onActions[0]?.name || "check",
      actions: onActions,
    },
  };
}

function readMetadataPair(payload: BotCockpitPayload, copy: Copy): DiffPair | null {
  const metadata = asRecord(payload.decision.metadata);
  const rlAb = asRecord(metadata.rl_ab);
  const direct = asRecord(
    rlAb.comparison ?? rlAb.diff ?? metadata.rl_ab_diff ?? metadata.rl_ab_compare ?? metadata.ab_variants ?? rlAb
  );
  const variantOff = normalizeVariant(
    direct.off ?? direct.rl_off ?? direct.control ?? direct.a ?? rlAb.off ?? rlAb.rl_off,
    copy.rlOff,
    false
  );
  const variantOn = normalizeVariant(
    direct.on ?? direct.rl_on ?? direct.treatment ?? direct.b ?? rlAb.on ?? rlAb.rl_on,
    copy.rlOn,
    true
  );

  if (variantOff && variantOn) {
    return {
      off: { ...variantOff, label: copy.rlOff },
      on: { ...variantOn, label: copy.rlOn },
      basis: "metadata",
    };
  }

  const variants = asArray(metadata.variants ?? metadata.policy_variants)
    .map((entry) => normalizeVariant(entry, copy.rlOff, false))
    .filter((entry): entry is DiffVariant => entry !== null);
  const off = variants.find((entry) => entry.rlEnabled === false || /off|control|baseline/i.test(entry.label));
  const on = variants.find((entry) => entry.rlEnabled === true || /on|treatment|rl/i.test(entry.label));
  if (off && on) {
    return {
      off: { ...off, label: copy.rlOff },
      on: { ...on, label: copy.rlOn },
      basis: "metadata",
    };
  }

  return null;
}

function ActionRow({
  action,
  highlight,
  accent,
}: {
  action: DiffAction;
  highlight: boolean;
  accent: "primary" | "secondary";
}) {
  const progress = clamp(normalizePercent(action.frequency), 0, 100);
  return (
    <Box
      sx={(theme) => ({
        px: 1.25,
        py: 1,
        borderRadius: 2.5,
        border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
        backgroundColor: highlight
          ? alpha(theme.palette[accent].main, 0.08)
          : alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.05 : 0.025),
      })}
    >
      <Stack spacing={0.75}>
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
          <Typography variant="body2" sx={{ fontWeight: highlight ? 700 : 600 }}>
            {prettifyAction(action.name)}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: "tabular-nums" }}>
            {formatPercent(action.frequency)}
          </Typography>
        </Stack>
        <LinearProgress
          variant="determinate"
          value={progress}
          color={accent}
          sx={(theme) => ({
            height: 7,
            borderRadius: 999,
            backgroundColor: alpha(theme.palette.text.primary, 0.12),
          })}
        />
        <Typography variant="caption" color="text.secondary" sx={{ fontVariantNumeric: "tabular-nums" }}>
          {formatEv(action.ev)}
        </Typography>
      </Stack>
    </Box>
  );
}

function VariantCard({
  variant,
  accent,
  copy,
}: {
  variant: DiffVariant;
  accent: "primary" | "secondary";
  copy: Copy;
}) {
  return (
    <Box
      sx={(theme) => ({
        borderRadius: 3,
        border: `1px solid ${alpha(theme.palette[accent].main, 0.22)}`,
        background: alpha(theme.palette[accent].main, 0.06),
        px: 1.5,
        py: 1.4,
      })}
    >
      <Stack spacing={1.2}>
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" useFlexGap flexWrap="wrap">
          <Chip
            size="small"
            color={accent}
            label={variant.label}
            icon={<PsychologyAltRoundedIcon fontSize="small" />}
          />
          <Chip
            size="small"
            variant="outlined"
            label={variant.source === "metadata" ? copy.basisMetadata : copy.basisEstimated}
          />
        </Stack>
        <Box>
          <Typography variant="caption" color="text.secondary">
            {copy.chosenAction}
          </Typography>
          <Typography variant="h6" sx={{ mt: 0.25 }}>
            {prettifyAction(variant.chosenAction)}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" variant="outlined" label={`${copy.heroEv} ${formatEv(variant.heroEv)}`} />
          <Chip size="small" variant="outlined" label={`${copy.confidence} ${formatPercent(variant.confidence)}`} />
        </Stack>
        <Divider />
        <Box>
          <Typography variant="caption" color="text.secondary">
            {copy.actionMix}
          </Typography>
          {variant.actions.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              {copy.noActionMix}
            </Typography>
          ) : (
            <Stack spacing={0.8} sx={{ mt: 0.9 }}>
              {variant.actions.slice(0, 3).map((action) => (
                <ActionRow
                  key={`${variant.label}-${action.name}`}
                  action={action}
                  highlight={action.name === variant.chosenAction}
                  accent={accent}
                />
              ))}
            </Stack>
          )}
        </Box>
      </Stack>
    </Box>
  );
}

export function RlDiffPanel({
  payload,
  locale = "en",
  title,
  subtitle,
  sx,
}: RlDiffPanelProps): JSX.Element {
  const copy = COPY[locale];
  const diffPair = readMetadataPair(payload, copy) ?? buildEstimatedPair(payload, copy);
  const deltaEv = diffPair.on.heroEv - diffPair.off.heroEv;
  const basisLabel = diffPair.basis === "metadata" ? copy.basisMetadata : copy.basisEstimated;

  return (
    <Card
      variant="outlined"
      sx={[
        (theme) => ({
          borderRadius: 5,
          overflow: "hidden",
          borderColor: alpha(theme.palette.text.primary, 0.08),
          background: theme.palette.background.paper,
          boxShadow:
            theme.palette.mode === "dark"
              ? "0 18px 44px rgba(0, 0, 0, 0.28)"
              : "0 10px 30px rgba(15, 23, 42, 0.06)",
        }),
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
    >
      <CardContent sx={{ p: { xs: 2.25, md: 2.75 } }}>
        <Stack spacing={2}>
          <Stack
            direction={{ xs: "column", lg: "row" }}
            spacing={1.5}
            justifyContent="space-between"
            alignItems={{ xs: "flex-start", lg: "center" }}
          >
            <Box>
              <Typography variant="overline" color="text.secondary">
                {copy.eyebrow}
              </Typography>
              <Typography variant="h5">{title ?? copy.title}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 820 }}>
                {subtitle ?? copy.subtitle}
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip icon={<CompareArrowsRoundedIcon fontSize="small" />} label={basisLabel} color="primary" variant="outlined" />
              <Chip label={`${copy.delta} ${formatDelta(deltaEv)}`} color={deltaEv >= 0 ? "success" : "warning"} />
            </Stack>
          </Stack>

          <Typography variant="body2" color="text.secondary">
            {copy.compactHint}
          </Typography>

          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", lg: "repeat(2, minmax(0, 1fr))" },
              gap: 1.5,
            }}
          >
            <VariantCard variant={diffPair.off} accent="secondary" copy={copy} />
            <VariantCard variant={diffPair.on} accent="primary" copy={copy} />
          </Box>

          {diffPair.basis === "estimated" ? (
            <Box
              sx={(theme) => ({
                borderRadius: 3,
                border: `1px dashed ${alpha(theme.palette.text.primary, 0.16)}`,
                background: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.04 : 0.02),
                px: 1.5,
                py: 1.2,
              })}
            >
              <Typography variant="caption" color="text.secondary">
                {copy.estimatedHint}
              </Typography>
            </Box>
          ) : null}
        </Stack>
      </CardContent>
    </Card>
  );
}
