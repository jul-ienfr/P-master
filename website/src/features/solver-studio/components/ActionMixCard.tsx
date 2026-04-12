import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { DecisionSnapshot } from "../../llm/types";

const actionTones = [
  {
    bar: "linear-gradient(90deg, #ffcb7a, #ff985e)",
    glow: "rgba(255, 179, 98, 0.18)",
  },
  {
    bar: "linear-gradient(90deg, #76e8d2, #3cbec5)",
    glow: "rgba(100, 223, 208, 0.18)",
  },
  {
    bar: "linear-gradient(90deg, #a8c4ff, #6f99ff)",
    glow: "rgba(126, 164, 255, 0.18)",
  },
  {
    bar: "linear-gradient(90deg, #d6a1ff, #8f78ff)",
    glow: "rgba(184, 148, 255, 0.16)",
  },
];

export interface ActionMixCardProps {
  decision?: DecisionSnapshot | null;
  title?: string;
  kicker?: string;
}

function asPercent(value: number | undefined, fallback = 0): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return fallback;
  }

  if (value > 1) {
    return Math.max(0, Math.min(100, value));
  }

  return Math.max(0, Math.min(100, value * 100));
}

function formatPercent(value: number | undefined): string {
  return `${asPercent(value).toFixed(0)}%`;
}

function formatEv(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "n/a";
  }

  return `${value >= 0 ? "+" : ""}${value.toFixed(2)} EV`;
}

export function ActionMixCard({
  decision,
  title = "Action mix",
  kicker = "Strategy",
}: ActionMixCardProps) {
  const alternatives = decision?.alternatives ?? [];
  const dominant = alternatives.reduce(
    (best, item) =>
      asPercent(item.frequency) > asPercent(best?.frequency) ? item : best,
    alternatives[0]
  );

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
      <CardContent sx={{ display: "grid", gap: 2 }}>
        <Box>
          <Typography variant="overline" sx={{ color: "#8fa8cc", letterSpacing: "0.14em" }}>
            {kicker}
          </Typography>
          <Typography variant="h6">{title}</Typography>
        </Box>

        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          alignItems={{ xs: "flex-start", sm: "center" }}
          justifyContent="space-between"
        >
          <Box>
            <Typography variant="body2" sx={{ color: "#95a8c8" }}>
              Preferred line
            </Typography>
            <Typography variant="h5">
              {decision?.chosenAction || dominant?.name || "Waiting for solve"}
            </Typography>
          </Box>
          <Box sx={{ textAlign: { xs: "left", sm: "right" } }}>
            <Typography variant="body2" sx={{ color: "#95a8c8" }}>
              Hero EV
            </Typography>
            <Typography variant="h6">{formatEv(decision?.heroEv)}</Typography>
          </Box>
        </Stack>

        <Stack spacing={1.15}>
          {alternatives.length > 0 ? (
            alternatives.map((action, index) => {
              const tone = actionTones[index % actionTones.length];
              const pct = asPercent(action.frequency, index === 0 ? 100 : 0);
              return (
                <Box
                  key={`${action.name}-${index}`}
                  sx={{
                    p: 1.25,
                    borderRadius: 3,
                    border: "1px solid rgba(160, 186, 220, 0.12)",
                    background: `linear-gradient(180deg, ${tone.glow}, rgba(255, 255, 255, 0.02))`,
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" spacing={1} sx={{ mb: 0.85 }}>
                    <Box>
                      <Typography variant="subtitle2">{action.name}</Typography>
                      <Typography variant="caption" sx={{ color: "#95a8c8" }}>
                        {typeof action.size === "number" ? `Size ${action.size}` : "Unspecified size"}
                      </Typography>
                    </Box>
                    <Box sx={{ textAlign: "right" }}>
                      <Typography variant="subtitle2">{formatPercent(action.frequency)}</Typography>
                      <Typography variant="caption" sx={{ color: "#95a8c8" }}>
                        {formatEv(action.ev)}
                      </Typography>
                    </Box>
                  </Stack>

                  <LinearProgress
                    variant="determinate"
                    value={pct}
                    sx={{
                      height: 10,
                      borderRadius: 999,
                      backgroundColor: "rgba(255, 255, 255, 0.06)",
                      "& .MuiLinearProgress-bar": {
                        borderRadius: 999,
                        backgroundImage: tone.bar,
                      },
                    }}
                  />
                </Box>
              );
            })
          ) : (
            <Typography variant="body2" sx={{ color: "#95a8c8" }}>
              No solver alternatives available yet.
            </Typography>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
