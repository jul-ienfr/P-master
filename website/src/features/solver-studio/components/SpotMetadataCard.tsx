import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { SpotSnapshot } from "../../llm/types";

export interface SpotMetadataCardProps {
  spot?: SpotSnapshot | null;
  title?: string;
  kicker?: string;
}

function formatCards(cards: SpotSnapshot["heroCards"] | SpotSnapshot["board"]): string {
  if (!cards || cards.length === 0) {
    return "Unknown";
  }

  return cards.map((card) => card.label ?? `${card.rank}${card.suit}`).join(" ");
}

function formatNumber(value: number | undefined, fallback = "Unknown"): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return fallback;
  }

  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

function renderList(values: string[] | undefined, fallback: string) {
  if (!values || values.length === 0) {
    return (
      <Typography variant="body2" sx={{ color: "#95a8c8" }}>
        {fallback}
      </Typography>
    );
  }

  return (
    <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
      {values.map((value) => (
        <Chip
          key={value}
          label={value}
          size="small"
          sx={{
            height: 28,
            backgroundColor: "rgba(255, 255, 255, 0.04)",
            border: "1px solid rgba(160, 186, 220, 0.14)",
            color: "#dfeafb",
          }}
        />
      ))}
    </Stack>
  );
}

export function SpotMetadataCard({
  spot,
  title = "Spot metadata",
  kicker = "Snapshot",
}: SpotMetadataCardProps) {
  const rows = [
    { label: "Street", value: spot?.street ?? "Unknown" },
    { label: "Hero position", value: spot?.heroPosition ?? "Unknown" },
    { label: "Pot", value: formatNumber(spot?.pot) },
    { label: "Effective stack", value: formatNumber(spot?.effectiveStack) },
    { label: "Players", value: formatNumber(spot?.numPlayers) },
    { label: "Source", value: spot?.source ?? "Unknown" },
  ];

  return (
    <Card
      variant="outlined"
      sx={{
        height: "100%",
        borderRadius: 4,
        borderColor: "rgba(160, 186, 220, 0.14)",
        background:
          "linear-gradient(180deg, rgba(11, 20, 33, 0.92), rgba(10, 17, 28, 0.82))",
      }}
    >
      <CardContent sx={{ display: "grid", gap: 2.25 }}>
        <Box>
          <Typography variant="overline" sx={{ color: "#8fa8cc", letterSpacing: "0.14em" }}>
            {kicker}
          </Typography>
          <Typography variant="h6">{title}</Typography>
        </Box>

        <Stack spacing={1}>
          {rows.map((row) => (
            <Stack
              key={row.label}
              direction="row"
              alignItems="center"
              justifyContent="space-between"
              sx={{
                py: 0.3,
                gap: 1,
              }}
            >
              <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.1em" }}>
                {row.label}
              </Typography>
              <Typography variant="body2" sx={{ color: "#ecf4ff", textTransform: "capitalize" }}>
                {row.value}
              </Typography>
            </Stack>
          ))}
        </Stack>

        <Divider sx={{ borderColor: "rgba(160, 186, 220, 0.12)" }} />

        <Box sx={{ display: "grid", gap: 1 }}>
          <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
            Hero cards
          </Typography>
          <Typography variant="body1" sx={{ color: "#ecf4ff", fontWeight: 700 }}>
            {formatCards(spot?.heroCards)}
          </Typography>
        </Box>

        <Box sx={{ display: "grid", gap: 1 }}>
          <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
            Board
          </Typography>
          <Typography variant="body1" sx={{ color: "#dbe8fa" }}>
            {formatCards(spot?.board)}
          </Typography>
        </Box>

        <Box sx={{ display: "grid", gap: 1 }}>
          <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
            Legal actions
          </Typography>
          {renderList(spot?.legalActions, "No legal actions exposed yet.")}
        </Box>

        <Box sx={{ display: "grid", gap: 1 }}>
          <Typography variant="caption" sx={{ color: "#8fa8cc", letterSpacing: "0.12em" }}>
            Action history
          </Typography>
          {renderList(spot?.actionHistory, "No prior actions recorded.")}
        </Box>
      </CardContent>
    </Card>
  );
}
