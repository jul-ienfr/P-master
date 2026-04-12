import React from "react";
import {
  alpha,
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
  type SxProps,
  type Theme,
} from "@mui/material";
import type { DecisionSnapshot, PokerCardSnapshot, SpotSnapshot } from "../../llm/types";
import type { CockpitHistoryViewMode } from "../types";

type LiveTableStage = SpotSnapshot["street"];
type LiveTableLocale = "en" | "fr";

export interface LiveTableSnapshotCardProps {
  spot: SpotSnapshot;
  decision?: DecisionSnapshot;
  title?: string;
  subtitle?: string;
  locale?: "en" | "fr";
  loading?: boolean;
  historyView?: CockpitHistoryViewMode;
  availableHistoryViews?: CockpitHistoryViewMode[];
  onHistoryViewChange?: (mode: CockpitHistoryViewMode) => void;
  sx?: SxProps<Theme>;
}

function getStageLabel(stage: LiveTableStage, locale: LiveTableLocale) {
  const labels: Record<LiveTableStage, string> =
    locale === "fr"
      ? {
          preflop: "Préflop",
          flop: "Flop",
          turn: "Turn",
          river: "River",
        }
      : {
          preflop: "Preflop",
          flop: "Flop",
          turn: "Turn",
          river: "River",
        };

  return labels[stage];
}

const suitSymbols: Record<string, string> = {
  s: "♠",
  spades: "♠",
  h: "♥",
  hearts: "♥",
  d: "♦",
  diamonds: "♦",
  c: "♣",
  clubs: "♣",
};

function formatMoney(value?: number): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: value % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function formatCard(card: PokerCardSnapshot): string {
  const label = card.label?.trim();
  if (label) {
    return label;
  }

  const rank = card.rank?.trim().toUpperCase() || "?";
  const suitKey = card.suit?.trim().toLowerCase() || "";
  const suit = suitSymbols[suitKey] ?? card.suit?.trim() ?? "•";
  return `${rank}${suit}`;
}

function getCardColor(card: PokerCardSnapshot): string {
  const suit = card.suit?.trim().toLowerCase() ?? "";
  if (suit === "h" || suit === "hearts" || suit === "d" || suit === "diamonds") {
    return "error.main";
  }
  return "text.primary";
}

function flattenMetadata(value: unknown, locale: LiveTableLocale): Array<{ label: string; value: string }> {
  if (!value || typeof value !== "object") {
    return [];
  }

  return Object.entries(value as Record<string, unknown>)
    .slice(0, 6)
    .map(([key, entry]) => {
      if (entry === null || entry === undefined) {
        return { label: key, value: "—" };
      }

      if (typeof entry === "string" || typeof entry === "number" || typeof entry === "boolean") {
        return { label: key, value: String(entry) };
      }

      if (Array.isArray(entry)) {
        return {
          label: key,
          value:
            locale === "fr"
              ? `${entry.length} élément${entry.length === 1 ? "" : "s"}`
              : `${entry.length} item${entry.length === 1 ? "" : "s"}`,
        };
      }

      return { label: key, value: locale === "fr" ? "objet" : "object" };
    });
}

function CardRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}): JSX.Element {
  return (
    <Stack direction="row" spacing={1.5} alignItems="baseline" justifyContent="space-between">
      <Typography variant="caption" sx={{ color: "text.secondary", textTransform: "uppercase", letterSpacing: 1 }}>
        {label}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 700, textAlign: "right" }}>
        {value}
      </Typography>
    </Stack>
  );
}

function RenderCards({
  cards,
  label,
  emptyLabel = "No cards",
  locale = "en",
}: {
  cards?: PokerCardSnapshot[];
  label: string;
  emptyLabel?: string;
  locale?: LiveTableLocale;
}): JSX.Element {
  return (
    <Stack spacing={1}>
      <Typography variant="caption" sx={{ color: "text.secondary", textTransform: "uppercase", letterSpacing: 1 }}>
        {label}
      </Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
        {cards?.length ? (
          cards.map((card, index) => (
            <Tooltip
              key={`${card.rank}-${card.suit}-${index}`}
              title={`${card.rank?.toUpperCase() ?? "?"} ${locale === "fr" ? "de" : "of"} ${card.suit ?? "?"}`}
            >
              <Box
                sx={(theme) => ({
                  minWidth: 52,
                  height: 64,
                  borderRadius: 2,
                  px: 1.25,
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexDirection: "column",
                  border: `1px solid ${alpha(theme.palette.text.primary, 0.12)}`,
                  background: theme.palette.background.paper,
                  boxShadow:
                    theme.palette.mode === "dark"
                      ? "0 10px 24px rgba(0, 0, 0, 0.24)"
                      : "0 6px 16px rgba(15, 23, 42, 0.06)",
                  color: getCardColor(card),
                })}
              >
                <Typography variant="subtitle1" sx={{ fontWeight: 900, lineHeight: 1 }}>
                  {formatCard(card)}
                </Typography>
                <Typography variant="caption" sx={{ mt: 0.25, color: "text.secondary", fontWeight: 700 }}>
                  {card.label ?? card.suit?.toUpperCase() ?? (locale === "fr" ? "CARTE" : "CARD")}
                </Typography>
              </Box>
            </Tooltip>
          ))
        ) : (
          <Box
            sx={(theme) => ({
              minHeight: 64,
              minWidth: 140,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 2,
              border: `1px dashed ${alpha(theme.palette.divider, 0.9)}`,
              color: "text.secondary",
              px: 2,
            })}
          >
            <Typography variant="body2">{emptyLabel}</Typography>
          </Box>
        )}
      </Stack>
    </Stack>
  );
}

export function LiveTableSnapshotCard({
  spot,
  decision,
  title = "Live Table Snapshot",
  subtitle = "Operator view of the current runtime spot",
  locale = "en",
  loading = false,
  historyView = "combined",
  availableHistoryViews = ["combined"],
  onHistoryViewChange,
  sx,
}: LiveTableSnapshotCardProps): JSX.Element {
  const copy =
    locale === "fr"
      ? {
          source: "Origine",
          players: "Joueurs",
          hero: "Héros",
          heroSeat: "Siège héros",
          legal: "Actions possibles",
          history: "Historique",
          decision: "Décision",
          observedHands: "Mains observées",
          gateConfidence: "Confiance sécurité",
          pending: "en attente",
          notReported: "Non remonté",
          runtime: "moteur local",
          heroCards: "Cartes héros",
          heroCardsHidden: "Cartes héros masquées",
          noCards: "Aucune carte",
          board: "Tableau",
          heroPosition: "Position héros",
          actionHistory: "Dernières actions",
          chosenAction: "Action choisie",
          metadata: "Infos utiles",
          ocrDetails: "Lecture écran",
          street: "Street",
          pot: "Pot",
          stack: "Stack",
          historyRuntime: "Live",
          historyPersisted: "Persisted",
          historyCombined: "Combined",
          nodes: (count: number) => `${count} action${count > 1 ? "s" : ""}`,
          ocrEngine: "Moteur OCR",
          ocrMode: "Mode OCR",
          ocrAgreement: "Accord OCR",
          ocrScore: "Score OCR",
          ocrCandidates: "Autres lectures OCR",
        }
      : {
          source: "Source",
          players: "Players",
          hero: "Hero",
          heroSeat: "Hero seat",
          legal: "Available actions",
          history: "History",
          decision: "Decision",
          observedHands: "Observed hands",
          gateConfidence: "Safety confidence",
          pending: "pending",
          notReported: "Not reported",
          runtime: "local engine",
          heroCards: "Hero Cards",
          heroCardsHidden: "Hero cards hidden",
          noCards: "No cards",
          board: "Board",
          heroPosition: "Hero position",
          actionHistory: "Latest actions",
          chosenAction: "Chosen action",
          metadata: "Useful info",
          ocrDetails: "Screen reading",
          ocrEngine: "OCR engine",
          ocrMode: "OCR mode",
          ocrAgreement: "OCR agreement",
          ocrScore: "OCR score",
          ocrCandidates: "OCR candidates",
          street: "Street",
          pot: "Pot",
          stack: "Stack",
          historyRuntime: "Exécution locale",
          historyPersisted: "Persisted",
          historyCombined: "Combined",
          nodes: (count: number) => `${count} nodes`,
        };
  const confidence = typeof spot.ocr === "object" && spot.ocr !== null
    ? (spot.ocr as Record<string, unknown>).confidence
    : undefined;
  const confidenceValue = typeof confidence === "number" ? confidence : undefined;
  const confidenceLabel =
    confidenceValue === undefined ? copy.notReported : `${Math.round(Math.max(0, Math.min(1, confidenceValue)) * 100)}%`;
  const gateConfidenceValue = decision?.gateDecision?.confidence;
  const gateConfidenceLabel =
    typeof gateConfidenceValue === "number"
      ? `${Math.round(Math.max(0, Math.min(1, gateConfidenceValue)) * 100)}%`
      : copy.notReported;
  const selectedEngine = typeof spot.ocr === "object" && spot.ocr !== null
    ? String((spot.ocr as Record<string, unknown>).selectedEngine ?? "")
    : "";
  const ocrMode = typeof spot.ocr === "object" && spot.ocr !== null
    ? String((spot.ocr as Record<string, unknown>).mode ?? "")
    : "";
  const ocrAgreement = typeof spot.ocr === "object" && spot.ocr !== null
    ? String((spot.ocr as Record<string, unknown>).agreement ?? "")
    : "";
  const historyViewLabels: Record<CockpitHistoryViewMode, string> = {
    runtime: copy.historyRuntime,
    persisted: copy.historyPersisted,
    combined: copy.historyCombined,
  };

  return (
    <Card
      elevation={0}
      sx={[
        (theme) => ({
          borderRadius: 4,
          border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
          background: theme.palette.background.paper,
          color: "text.primary",
          overflow: "hidden",
          boxShadow:
            theme.palette.mode === "dark"
              ? "0 18px 44px rgba(0, 0, 0, 0.28)"
              : "0 10px 30px rgba(15, 23, 42, 0.06)",
        }),
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
    >
      {loading ? <LinearProgress /> : null}
      <CardContent sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "flex-start", sm: "center" }} justifyContent="space-between">
            <Box>
              <Typography variant="overline" sx={{ color: "text.secondary", letterSpacing: 1.2 }}>
                {title}
              </Typography>
              <Typography variant="h5" sx={{ fontWeight: 900, lineHeight: 1.1, mt: 0.5 }}>
                {getStageLabel(spot.street, locale)}
              </Typography>
              <Typography variant="body2" sx={{ color: "text.secondary", mt: 0.75 }}>
                {subtitle}
              </Typography>
            </Box>

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip
                label={`OCR ${confidenceLabel}`}
                size="small"
                sx={{ fontWeight: 700 }}
                variant="outlined"
              />
              <Chip
                label={`${copy.pot} ${formatMoney(spot.pot)}`}
                size="small"
                sx={{ fontWeight: 700 }}
                variant="outlined"
              />
              <Chip
                label={`${copy.stack} ${formatMoney(spot.effectiveStack)}`}
                size="small"
                sx={{ fontWeight: 700 }}
                variant="outlined"
              />
            </Stack>
          </Stack>

          <Stack spacing={2}>
            <RenderCards label={copy.heroCards} cards={spot.heroCards} emptyLabel={copy.heroCardsHidden} locale={locale} />
            <RenderCards label={copy.board} cards={spot.board} emptyLabel={copy.noCards} locale={locale} />
          </Stack>

          <Divider sx={(theme) => ({ borderColor: alpha(theme.palette.text.primary, 0.08) })} />

          <Stack spacing={2} direction={{ xs: "column", md: "row" }}>
            <Box sx={{ flex: 1 }}>
              <Stack spacing={1.25}>
                <CardRow label={copy.heroPosition} value={spot.heroPosition ?? "—"} />
                <CardRow label={copy.players} value={spot.numPlayers ?? "—"} />
                <CardRow label={copy.legal} value={spot.legalActions?.length ? spot.legalActions.join(" · ") : "—"} />
                <Stack spacing={0.75}>
                  <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" useFlexGap flexWrap="wrap">
                    <Typography variant="caption" sx={{ color: "text.secondary", textTransform: "uppercase", letterSpacing: 1 }}>
                      {copy.actionHistory}
                    </Typography>
                    {availableHistoryViews.length > 1 ? (
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
                    ) : null}
                  </Stack>
                  <Typography variant="body2" sx={{ fontWeight: 700, textAlign: "right" }}>
                    {spot.actionHistory?.length ? spot.actionHistory.slice(-3).join(" · ") : "—"}
                  </Typography>
                </Stack>
              </Stack>
            </Box>

            <Box sx={{ flex: 1 }}>
              <Stack spacing={1.25}>
                <CardRow label={copy.source} value={spot.source ?? copy.runtime} />
                <CardRow label={copy.street} value={getStageLabel(spot.street, locale)} />
                <CardRow label="OCR" value={confidenceLabel} />
                <CardRow label={copy.gateConfidence} value={gateConfidenceLabel} />
                <CardRow label={copy.chosenAction} value={decision?.chosenAction ?? copy.pending} />
              </Stack>
            </Box>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
