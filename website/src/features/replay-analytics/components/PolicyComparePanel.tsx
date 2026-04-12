import CompareArrowsRoundedIcon from "@mui/icons-material/CompareArrowsRounded";
import ChevronLeftRoundedIcon from "@mui/icons-material/ChevronLeftRounded";
import ChevronRightRoundedIcon from "@mui/icons-material/ChevronRightRounded";
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";
import InsightsRoundedIcon from "@mui/icons-material/InsightsRounded";
import TuneRoundedIcon from "@mui/icons-material/TuneRounded";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TableSortLabel from "@mui/material/TableSortLabel";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useState } from "react";
import type { SxProps, Theme } from "@mui/material/styles";
import { alpha } from "@mui/material/styles";
import { getPolicyCompareCopy } from "../../../lib/workstationI18n";

import type { PolicyCompareAggregate, ReplayTimelineSpot } from "./types";

export interface PolicyComparePanelProps {
  locale?: "en" | "fr";
  selectedSpot?: ReplayTimelineSpot;
  aggregate?: PolicyCompareAggregate;
  title?: string;
  subtitle?: string;
  sx?: SxProps<Theme>;
}

type Copy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  waiting: string;
  waitingHelp: string;
  selected: string;
  aggregate: string;
  aggregateFocus: string;
  session: string;
  aggregateWaiting: string;
  scope: string;
  scopeHint: string;
  compared: string;
  avgDelta: string;
  strongest: string;
  focus: string;
  coverage: string;
  priorities: string;
  analysisHints: string;
  delta: string;
  action: string;
  confidence: string;
  noSignal: string;
  signalTitle: string;
  signalSubtitle: string;
  spotMeta: string;
  recommendation: string;
  comparisons: string;
  pairwise: string;
  pairwiseHint: string;
  pairLabel: string;
  pairDetail: string;
  pairCompactNav: string;
  pairTable: string;
  pairFilterSearch: string;
  pairFilterStreet: string;
  pairFilterSignal: string;
  pairFilterPolicyPair: string;
  pairFilterGate: string;
  pairFilterDeltaMin: string;
  pairFilterActionOnly: string;
  pairFilterShown: string;
  pairFilterAll: string;
  pairSort: string;
  pairSortImpact: string;
  pairSortDelta: string;
  pairSortConfidence: string;
  pairSortPolicy: string;
  pairSortRecent: string;
  pairSortTitle: string;
  pairSortActive: string;
  pairSortAsc: string;
  pairSortDesc: string;
  pairVisibleColumns: string;
  pairVisibleColumnsHint: string;
  pairColSpot: string;
  pairColPolicy: string;
  pairColSignal: string;
  pairColImpact: string;
  pairColDelta: string;
  pairColConfidence: string;
  pairColContext: string;
  pairColUpdated: string;
  pairNoRows: string;
  pairRowsPerPage: string;
  pairPageRange: string;
  pairExportCsv: string;
  pairExportEmpty: string;
  pairExportScope: string;
  pairExportPage: string;
  pairExportFiltered: string;
  pairExportAll: string;
  contexts: string;
  noPairMeta: string;
  highlights: string;
  showMore: string;
  hide: string;
};

const COPY: Record<"en" | "fr", Copy> = {
  fr: getPolicyCompareCopy("fr"),
  en: getPolicyCompareCopy("en"),
};

function getPairSignalCount(item: PolicyCompareAggregate["pairwiseComparisons"] extends Array<infer T> ? T : never): number {
  return [item.deltaEv, item.actionShift, item.confidenceShift].filter(Boolean).length;
}

function getPairMeta(item: PolicyCompareAggregate["pairwiseComparisons"] extends Array<infer T> ? T : never): string {
  return [item.street, item.action, item.canonicalSpot].filter(Boolean).join(" · ");
}

function getPairPreview(item: PolicyCompareAggregate["pairwiseComparisons"] extends Array<infer T> ? T : never, copy: Copy): string {
  return item.actionShift ?? item.deltaEv ?? item.confidenceShift ?? item.impactLabel ?? item.gateResult ?? copy.noPairMeta;
}

function getPairPolicyLabel(item: PolicyCompareAggregate["pairwiseComparisons"] extends Array<infer T> ? T : never): string {
  if (item.policyPairLabel?.trim()) {
    return item.policyPairLabel;
  }

  if (item.policyA?.trim() && item.policyB?.trim()) {
    return `${item.policyA} vs ${item.policyB}`;
  }

  return item.policyPairKey ?? "default";
}

function getPairPolicyMeta(item: PolicyCompareAggregate["pairwiseComparisons"] extends Array<infer T> ? T : never): string {
  if (item.policyA?.trim() && item.policyB?.trim()) {
    return `${item.policyA} vs ${item.policyB}`;
  }

  if (item.policyPairLabel?.trim() && item.policyPairKey?.trim() && item.policyPairLabel !== item.policyPairKey) {
    return item.policyPairKey;
  }

  return item.policyPairKey ?? "";
}

function parseSignedMetric(value?: string): number | null {
  if (!value) {
    return null;
  }

  const match = value.replace(/,/g, ".").match(/[-+]?\d+(?:\.\d+)?/);
  if (!match) {
    return null;
  }

  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function getPairPrimarySignal(item: PolicyCompareAggregate["pairwiseComparisons"] extends Array<infer T> ? T : never, copy: Copy): string {
  if (item.actionShift) {
    return `${copy.action}: ${item.actionShift}`;
  }
  if (item.deltaEv) {
    return `${copy.delta}: ${item.deltaEv}`;
  }
  if (item.confidenceShift) {
    return `${copy.confidence}: ${item.confidenceShift}`;
  }
  return item.impactLabel ?? copy.noSignal;
}

function getPairTimestampScore(item: PolicyCompareAggregate["pairwiseComparisons"] extends Array<infer T> ? T : never): number {
  if (!item.timestamp) {
    return -1;
  }

  const parsed = Date.parse(item.timestamp);
  return Number.isFinite(parsed) ? parsed : -1;
}

type PairSignalFilter = "all" | "delta" | "action" | "confidence";

type PairSortKey = "impact" | "delta" | "confidence" | "policy" | "recent" | "title";

type PairTableColumnKey = "title" | "policy" | "impact" | "delta" | "confidence" | "recent";

type PairVisibleColumnKey = "policy" | "signal" | "impact" | "delta" | "confidence" | "context" | "recent";

type PairSortDirection = "asc" | "desc";

type PairExportScope = "page" | "filtered";

const DEFAULT_PAIR_VISIBLE_COLUMNS: PairVisibleColumnKey[] = ["policy", "signal", "impact", "delta", "confidence", "context", "recent"];

const PAIR_ROWS_PER_PAGE_OPTIONS = [8, 12, 20, 40, 80];

function getPrimarySignal(spot: ReplayTimelineSpot, copy: Copy): string {
  if (spot.rlDiffSummary?.actionShift) {
    return `${copy.action}: ${spot.rlDiffSummary.actionShift}`;
  }
  if (spot.rlDiffSummary?.deltaEv) {
    return `${copy.delta}: ${spot.rlDiffSummary.deltaEv}`;
  }
  if (spot.rlDiffSummary?.confidenceShift) {
    return `${copy.confidence}: ${spot.rlDiffSummary.confidenceShift}`;
  }
  return copy.noSignal;
}

function getDrillDownLabel(count: number, copy: Copy, expanded: boolean): string {
  const action = expanded ? copy.hide : copy.showMore;
  return `${action} (${count})`;
}

function getPairConfidenceScore(item: PolicyCompareAggregate["pairwiseComparisons"] extends Array<infer T> ? T : never): number {
  return parseSignedMetric(item.confidenceShift) ?? parseSignedMetric(item.confidence) ?? -1;
}

function getPairSortLabel(sort: PairSortKey, copy: Copy): string {
  if (sort === "delta") {
    return copy.pairSortDelta;
  }
  if (sort === "confidence") {
    return copy.pairSortConfidence;
  }
  if (sort === "policy") {
    return copy.pairSortPolicy;
  }
  if (sort === "recent") {
    return copy.pairSortRecent;
  }
  if (sort === "title") {
    return copy.pairSortTitle;
  }
  return copy.pairSortImpact;
}

function getPairSortDirectionLabel(direction: PairSortDirection, copy: Copy): string {
  return direction === "asc" ? copy.pairSortAsc : copy.pairSortDesc;
}

function getDefaultPairSortDirection(sort: PairSortKey): PairSortDirection {
  return sort === "policy" || sort === "title" ? "asc" : "desc";
}

function getPairColumnLabel(column: PairVisibleColumnKey, copy: Copy): string {
  if (column === "policy") {
    return copy.pairColPolicy;
  }
  if (column === "signal") {
    return copy.pairColSignal;
  }
  if (column === "impact") {
    return copy.pairColImpact;
  }
  if (column === "delta") {
    return copy.pairColDelta;
  }
  if (column === "confidence") {
    return copy.pairColConfidence;
  }
  if (column === "context") {
    return copy.pairColContext;
  }
  return copy.pairColUpdated;
}

function escapeCsvValue(value: string): string {
  const normalized = value.replace(/"/g, '""');
  return /[",\n;]/.test(normalized) ? `"${normalized}"` : normalized;
}

export function PolicyComparePanel({
  locale = "en",
  selectedSpot,
  aggregate,
  title,
  subtitle,
  sx,
}: PolicyComparePanelProps) {
  const copy = COPY[locale];
  const [expanded, setExpanded] = useState({ comparisons: false, highlights: false });
  const hasCompareSignal = Boolean(
    selectedSpot?.rlDiffSummary?.deltaEv ||
      selectedSpot?.rlDiffSummary?.actionShift ||
      selectedSpot?.rlDiffSummary?.confidenceShift
  );
  const hasAggregateSignal = Boolean(aggregate && aggregate.comparedSpots > 0);
  const comparisonItems = aggregate?.comparisons ?? [];
  const highlightItems = aggregate?.highlights ?? [];
  const priorityLabels = aggregate?.priorityLabels ?? [];
  const analysisHints = aggregate?.analysisHints ?? [];
  const scopeMeta = [aggregate?.scopeBadge, aggregate?.sessionLabel].filter(Boolean).join(" · ");
  const pairwiseItems = aggregate?.pairwiseComparisons?.length ? aggregate.pairwiseComparisons : comparisonItems;
  const [activePairIndex, setActivePairIndex] = useState(0);
  const [pairFilter, setPairFilter] = useState("");
  const [pairStreetFilter, setPairStreetFilter] = useState("all");
  const [pairSignalFilter, setPairSignalFilter] = useState<PairSignalFilter>("all");
  const [pairPolicyFilter, setPairPolicyFilter] = useState("all");
  const [pairGateFilter, setPairGateFilter] = useState("all");
  const [pairDeltaMinFilter, setPairDeltaMinFilter] = useState("0");
  const [pairActionShiftOnly, setPairActionShiftOnly] = useState("false");
  const [pairSort, setPairSort] = useState<PairSortKey>("impact");
  const [pairSortDirection, setPairSortDirection] = useState<PairSortDirection>("desc");
  const [pairPage, setPairPage] = useState(0);
  const [pairRowsPerPage, setPairRowsPerPage] = useState(8);
  const [pairExportScope, setPairExportScope] = useState<PairExportScope>("page");
  const [visiblePairColumns, setVisiblePairColumns] = useState<PairVisibleColumnKey[]>(DEFAULT_PAIR_VISIBLE_COLUMNS);
  const pairStreetOptions = useMemo(
    () => Array.from(new Set(pairwiseItems.map((item) => item.street).filter((value): value is string => Boolean(value)))).sort(),
    [pairwiseItems],
  );
  const pairPolicyOptions = useMemo(
    () =>
      Array.from(
        new Set(pairwiseItems.map((item) => getPairPolicyLabel(item)).filter((value): value is string => value.trim().length > 0)),
      ).sort(),
    [pairwiseItems],
  );
  const pairGateOptions = useMemo(
    () => Array.from(new Set(pairwiseItems.map((item) => item.gateResult).filter((value): value is string => Boolean(value)))).sort(),
    [pairwiseItems],
  );
  const filteredPairwiseItems = useMemo(() => {
    const normalizedFilter = pairFilter.trim().toLowerCase();
    const minDelta = Math.max(0, parseSignedMetric(pairDeltaMinFilter) ?? 0);

    return pairwiseItems.filter((item) => {
      const matchesText =
        normalizedFilter.length === 0 ||
        [item.title, item.note, item.canonicalSpot, item.action, item.policyPairLabel]
          .filter(Boolean)
          .some((value) => value!.toLowerCase().includes(normalizedFilter));
      const matchesStreet = pairStreetFilter === "all" || item.street === pairStreetFilter;
      const matchesSignal =
        pairSignalFilter === "all" ||
        (pairSignalFilter === "delta" && Boolean(item.deltaEv)) ||
        (pairSignalFilter === "action" && Boolean(item.actionShift)) ||
        (pairSignalFilter === "confidence" && Boolean(item.confidenceShift));
      const matchesPolicyPair = pairPolicyFilter === "all" || getPairPolicyLabel(item) === pairPolicyFilter;
      const matchesGate = pairGateFilter === "all" || item.gateResult === pairGateFilter;
      const matchesDelta = Math.abs(parseSignedMetric(item.deltaEv) ?? 0) >= minDelta;
      const matchesActionOnly = pairActionShiftOnly !== "true" || Boolean(item.actionShift);

      return matchesText && matchesStreet && matchesSignal && matchesPolicyPair && matchesGate && matchesDelta && matchesActionOnly;
    });
  }, [pairActionShiftOnly, pairDeltaMinFilter, pairFilter, pairGateFilter, pairPolicyFilter, pairSignalFilter, pairStreetFilter, pairwiseItems]);
  const sortedFilteredPairwiseItems = useMemo(() => {
    const sortedItems = [...filteredPairwiseItems].sort((left, right) => {
      if (pairSort === "title") {
        return left.title.localeCompare(right.title);
      }

      if (pairSort === "policy") {
        const policyCompare = getPairPolicyLabel(left).localeCompare(getPairPolicyLabel(right));
        if (policyCompare !== 0) {
          return policyCompare;
        }
      }

      if (pairSort === "recent") {
        return getPairTimestampScore(right) - getPairTimestampScore(left);
      }

      if (pairSort === "delta") {
        return Math.abs(parseSignedMetric(right.deltaEv) ?? -1) - Math.abs(parseSignedMetric(left.deltaEv) ?? -1);
      }

      if (pairSort === "confidence") {
        return getPairConfidenceScore(right) - getPairConfidenceScore(left);
      }

      const impactGap = (right.impactScore ?? -1) - (left.impactScore ?? -1);
      if (impactGap !== 0) {
        return impactGap;
      }

      return Math.abs(parseSignedMetric(right.deltaEv) ?? -1) - Math.abs(parseSignedMetric(left.deltaEv) ?? -1);
    });

    return pairSortDirection === "asc" ? sortedItems.reverse() : sortedItems;
  }, [filteredPairwiseItems, pairSort, pairSortDirection]);
  const activePair = pairwiseItems[activePairIndex];
  const activePairMeta = activePair ? getPairMeta(activePair) : "";
  const activePairSignalCount = activePair ? getPairSignalCount(activePair) : 0;
  const pairPageCount = Math.max(1, Math.ceil(sortedFilteredPairwiseItems.length / pairRowsPerPage));
  const currentPairPage = Math.min(pairPage, pairPageCount - 1);
  const paginatedFilteredPairwiseItems = useMemo(() => {
    const start = currentPairPage * pairRowsPerPage;
    return sortedFilteredPairwiseItems.slice(start, start + pairRowsPerPage);
  }, [currentPairPage, pairRowsPerPage, sortedFilteredPairwiseItems]);
  const pairRangeStart = sortedFilteredPairwiseItems.length === 0 ? 0 : currentPairPage * pairRowsPerPage + 1;
  const pairRangeEnd = Math.min(sortedFilteredPairwiseItems.length, (currentPairPage + 1) * pairRowsPerPage);

  const handlePairSortChange = (nextSort: PairSortKey) => {
    setPairSort(nextSort);
    setPairSortDirection(getDefaultPairSortDirection(nextSort));
    setPairPage(0);
  };

  const handlePairHeaderSort = (column: PairTableColumnKey) => {
    const nextSortByColumn: Record<PairTableColumnKey, PairSortKey> = {
      title: "title",
      policy: "policy",
      impact: "impact",
      delta: "delta",
      confidence: "confidence",
      recent: "recent",
    };

    const nextSort = nextSortByColumn[column];
    if (pairSort === nextSort) {
      setPairSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      setPairPage(0);
      return;
    }

    setPairSort(nextSort);
    setPairSortDirection(getDefaultPairSortDirection(nextSort));
    setPairPage(0);
  };

  const togglePairColumn = (column: PairVisibleColumnKey) => {
    setVisiblePairColumns((current) => {
      if (current.includes(column)) {
        return current.filter((entry) => entry !== column);
      }

      return [...current, column];
    });
  };

  const handlePairExportCsv = () => {
    const exportItems = pairExportScope === "page" ? paginatedFilteredPairwiseItems : sortedFilteredPairwiseItems;
    if (exportItems.length === 0) {
      return;
    }

    const filterSummary = [
      pairFilter.trim() ? `${copy.pairFilterSearch}: ${pairFilter.trim()}` : "",
      pairStreetFilter !== "all" ? `${copy.pairFilterStreet}: ${pairStreetFilter}` : "",
      pairPolicyFilter !== "all" ? `${copy.pairFilterPolicyPair}: ${pairPolicyFilter}` : "",
      pairGateFilter !== "all" ? `${copy.pairFilterGate}: ${pairGateFilter}` : "",
      pairSignalFilter !== "all" ? `${copy.pairFilterSignal}: ${pairSignalFilter}` : "",
      pairActionShiftOnly === "true" ? `${copy.pairFilterActionOnly}: ${copy.action}` : "",
      Number(pairDeltaMinFilter) > 0 ? `${copy.pairFilterDeltaMin}: ${pairDeltaMinFilter}` : "",
      `${copy.pairSortActive}: ${getPairSortLabel(pairSort, copy)} (${getPairSortDirectionLabel(pairSortDirection, copy)})`,
    ].filter((value) => value.length > 0);

    const rows = [
      [copy.pairExportScope, pairExportScope === "page" ? copy.pairExportPage : copy.pairExportFiltered],
      [copy.scope, aggregate?.scopeLabel ?? selectedSpot?.title ?? ""],
      [copy.pairFilterSearch, filterSummary.join(" | ")],
      [],
      [
        copy.pairColSpot,
        copy.pairColPolicy,
        copy.pairColSignal,
        copy.pairColImpact,
        copy.pairColDelta,
        copy.pairColConfidence,
        copy.pairColContext,
        copy.pairColUpdated,
        copy.action,
        copy.pairFilterGate,
        copy.recommendation,
      ],
      ...exportItems.map((item) => [
        item.title,
        getPairPolicyLabel(item),
        getPairPrimarySignal(item, copy),
        item.impactLabel ?? item.impactScore?.toString() ?? "",
        item.deltaEv ?? "",
        item.confidence ?? item.confidenceShift ?? "",
        getPairMeta(item) || item.gateResult || "",
        item.timestamp ?? "",
        item.action ?? "",
        item.gateResult ?? "",
        item.note ?? "",
      ]),
    ];

    const csv = rows.map((row) => row.map((value) => escapeCsvValue(value)).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const objectUrl = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `policy-compare-pairwise-${locale}.csv`;
    anchor.click();
    window.URL.revokeObjectURL(objectUrl);
  };

  useEffect(() => {
    setActivePairIndex(0);
  }, [selectedSpot?.id, aggregate?.scopeLabel, pairwiseItems.length]);

  useEffect(() => {
    setPairPage(0);
  }, [pairActionShiftOnly, pairDeltaMinFilter, pairFilter, pairGateFilter, pairPolicyFilter, pairSignalFilter, pairSort, pairSortDirection, pairStreetFilter]);

  useEffect(() => {
    if (pairwiseItems.length === 0) {
      if (activePairIndex !== 0) {
        setActivePairIndex(0);
      }
      return;
    }
    if (activePairIndex >= pairwiseItems.length) {
      setActivePairIndex(pairwiseItems.length - 1);
    }
  }, [activePairIndex, pairwiseItems.length]);

  useEffect(() => {
    if (!activePair || sortedFilteredPairwiseItems.some((item) => item.id === activePair.id)) {
      return;
    }

    const nextPair = sortedFilteredPairwiseItems[0];
    if (!nextPair) {
      return;
    }

    const nextIndex = pairwiseItems.findIndex((item) => item.id === nextPair.id);
    if (nextIndex >= 0 && nextIndex !== activePairIndex) {
      setActivePairIndex(nextIndex);
    }
  }, [activePair, activePairIndex, pairwiseItems, sortedFilteredPairwiseItems]);

  return (
    <Card
      variant="outlined"
      sx={[
        (theme) => ({
          borderRadius: 5,
          borderColor: alpha(theme.palette.secondary.main, 0.16),
          background: `
            radial-gradient(circle at top right, ${alpha(theme.palette.secondary.main, 0.14)}, transparent 34%),
            ${
              theme.palette.mode === "dark"
                ? "linear-gradient(180deg, rgba(12,17,29,0.96), rgba(9,14,24,0.94))"
                : "linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248,249,252,0.99))"
            }
          `,
        }),
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
    >
      <CardContent sx={{ p: { xs: 2.25, md: 2.5 }, "&:last-child": { pb: { xs: 2.25, md: 2.5 } } }}>
        <Stack spacing={2}>
              <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} justifyContent="space-between">
            <Box>
              <Typography variant="overline" color="text.secondary">
                {title ?? copy.eyebrow}
              </Typography>
              <Typography variant="h6" sx={{ mt: 0.25 }}>
                {copy.title}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 720 }}>
                {subtitle ?? copy.subtitle}
              </Typography>
            </Box>
            {selectedSpot || hasAggregateSignal ? (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip size="small" color="secondary" icon={<CompareArrowsRoundedIcon fontSize="small" />} label={copy.aggregateFocus} />
                {aggregate?.scopeBadge ? <Chip size="small" variant="outlined" label={aggregate.scopeBadge} /> : null}
                {aggregate?.scopeLabel ? <Chip size="small" variant="outlined" label={aggregate.scopeLabel} /> : null}
                {selectedSpot.street ? <Chip size="small" variant="outlined" label={selectedSpot.street} /> : null}
                {selectedSpot.action ? <Chip size="small" variant="outlined" label={selectedSpot.action} /> : null}
              </Stack>
            ) : null}
          </Stack>

          {!selectedSpot && !hasAggregateSignal ? (
            <Alert severity="info" variant="outlined">
              <strong>{copy.waiting}</strong> {copy.waitingHelp}
            </Alert>
          ) : (
            <Box
              sx={{
                display: "grid",
                gap: 1.5,
                gridTemplateColumns: { xs: "1fr", xl: "minmax(0, 1.1fr) minmax(280px, 0.9fr)" },
                alignItems: "start",
              }}
            >
              <Stack
                spacing={1.5}
                sx={(theme) => ({
                  p: 1.75,
                  borderRadius: 4,
                  border: `1px solid ${alpha(theme.palette.secondary.main, 0.14)}`,
                  backgroundColor: alpha(theme.palette.secondary.main, 0.06),
                })}
                >
                  <Box>
                    <Typography variant="subtitle2">{copy.aggregate}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.35 }}>
                      {hasAggregateSignal ? copy.signalSubtitle : copy.aggregateWaiting}
                    </Typography>
                  </Box>
                  {aggregate?.coverageSummary ? (
                    <Typography variant="body2" color="text.secondary">
                      <strong>{copy.coverage}:</strong> {aggregate.coverageSummary}
                    </Typography>
                  ) : null}
                  <Typography variant="body1" sx={{ fontWeight: 600 }}>
                    {hasAggregateSignal
                      ? aggregate?.topActionShift ?? aggregate?.strongestDeltaEv ?? aggregate?.averageDeltaEv ?? copy.aggregateWaiting
                      : copy.aggregateWaiting}
                  </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {aggregate ? (
                    <Chip size="small" color="secondary" variant="outlined" label={`${copy.compared} ${aggregate.comparedSpots}`} />
                  ) : null}
                  {aggregate?.averageDeltaEv ? (
                    <Chip size="small" variant="outlined" label={`${copy.avgDelta} ${aggregate.averageDeltaEv}`} />
                  ) : null}
                  {aggregate?.strongestDeltaEv ? (
                    <Chip size="small" variant="outlined" label={`${copy.strongest} ${aggregate.strongestDeltaEv}`} />
                  ) : null}
                  {aggregate?.actionShiftSpots ? (
                    <Chip size="small" variant="outlined" label={`${copy.action} ${aggregate.actionShiftSpots}`} />
                  ) : null}
                  {aggregate?.confidenceShiftSpots ? (
                    <Chip size="small" variant="outlined" label={`${copy.confidence} ${aggregate.confidenceShiftSpots}`} />
                  ) : null}
                  {aggregate?.distinctContexts ? (
                    <Chip size="small" variant="outlined" label={`${copy.contexts} ${aggregate.distinctContexts}`} />
                  ) : null}
                  {!hasAggregateSignal ? <Chip size="small" variant="outlined" label={copy.aggregateWaiting} /> : null}
                </Stack>
              </Stack>

              <Stack
                spacing={1.25}
                sx={(theme) => ({
                  p: 1.75,
                  borderRadius: 4,
                  border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                  backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.035 : 0.02),
                })}
                >
                <Stack direction="row" spacing={1} alignItems="center">
                  <TuneRoundedIcon color="action" fontSize="small" />
                  <Typography variant="subtitle2">{selectedSpot ? copy.selected : copy.aggregate}</Typography>
                </Stack>
                <Typography variant="body2">{selectedSpot?.title ?? aggregate?.scopeLabel ?? copy.aggregateFocus}</Typography>
                <Stack direction="row" spacing={1} alignItems="center">
                  <InsightsRoundedIcon color="action" fontSize="small" />
                  <Typography variant="subtitle2">{selectedSpot ? copy.spotMeta : copy.scope}</Typography>
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {selectedSpot
                    ? [selectedSpot.canonicalSpot, selectedSpot.gateResult].filter(Boolean).join(" · ") || copy.waitingHelp
                    : [aggregate?.scopeLabel, aggregate?.topContext].filter(Boolean).join(" · ") || copy.aggregateWaiting}
                </Typography>
                {!selectedSpot && scopeMeta ? (
                  <Typography variant="caption" color="text.secondary">
                    {copy.session}: {scopeMeta}
                  </Typography>
                ) : null}
                {selectedSpot ? (
                  <>
                    <Typography variant="subtitle2">{copy.focus}</Typography>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {getPrimarySignal(selectedSpot, copy)}
                    </Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      {selectedSpot.rlDiffSummary?.deltaEv ? (
                        <Chip size="small" color="secondary" variant="outlined" label={`${copy.delta} ${selectedSpot.rlDiffSummary.deltaEv}`} />
                      ) : null}
                      {selectedSpot.rlDiffSummary?.actionShift ? (
                        <Chip size="small" variant="outlined" label={`${copy.action} ${selectedSpot.rlDiffSummary.actionShift}`} />
                      ) : null}
                      {selectedSpot.rlDiffSummary?.confidenceShift ? (
                        <Chip size="small" variant="outlined" label={`${copy.confidence} ${selectedSpot.rlDiffSummary.confidenceShift}`} />
                      ) : null}
                      {!hasCompareSignal ? <Chip size="small" variant="outlined" label={copy.noSignal} /> : null}
                    </Stack>
                  </>
                ) : null}
                {selectedSpot?.note || aggregate?.topRecommendation ? (
                  <>
                    <Typography variant="subtitle2">{copy.recommendation}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selectedSpot?.note ?? aggregate?.topRecommendation}
                    </Typography>
                  </>
                ) : null}
                {priorityLabels.length > 0 ? (
                  <>
                    <Typography variant="subtitle2">{copy.priorities}</Typography>
                    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                      {priorityLabels.map((label) => (
                        <Chip key={label} size="small" variant="outlined" label={label} />
                      ))}
                    </Stack>
                  </>
                ) : null}
                {analysisHints.length > 0 ? (
                  <>
                    <Typography variant="subtitle2">{copy.analysisHints}</Typography>
                    <Stack spacing={0.5}>
                      {analysisHints.map((hint) => (
                        <Typography key={hint} variant="caption" color="text.secondary">
                          {hint}
                        </Typography>
                      ))}
                    </Stack>
                  </>
                ) : (
                  <Typography variant="caption" color="text.secondary">
                    {copy.scopeHint}
                  </Typography>
                )}
                {activePair ? (
                  <Box
                    sx={(theme) => ({
                      p: 1.25,
                      borderRadius: 3,
                      border: `1px solid ${alpha(theme.palette.secondary.main, 0.14)}`,
                      backgroundColor: alpha(theme.palette.secondary.main, 0.05),
                    })}
                  >
                    <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                      <Box sx={{ minWidth: 0, flex: 1 }}>
                        <Typography variant="subtitle2">{copy.pairwise}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {copy.pairwiseHint}
                        </Typography>
                      </Box>
                      <Stack direction="row" spacing={0.25} alignItems="center">
                        <IconButton
                          size="small"
                          onClick={() => setActivePairIndex((current) => Math.max(0, current - 1))}
                          disabled={activePairIndex === 0}
                          aria-label={`${copy.pairwise} previous`}
                        >
                          <ChevronLeftRoundedIcon fontSize="small" />
                        </IconButton>
                        <Typography variant="caption" color="text.secondary" sx={{ minWidth: 54, textAlign: "center" }}>
                          {copy.pairLabel} {activePairIndex + 1}/{pairwiseItems.length}
                        </Typography>
                        <IconButton
                          size="small"
                          onClick={() => setActivePairIndex((current) => Math.min(pairwiseItems.length - 1, current + 1))}
                          disabled={activePairIndex >= pairwiseItems.length - 1}
                          aria-label={`${copy.pairwise} next`}
                        >
                          <ChevronRightRoundedIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    </Stack>
                    <Typography variant="body2" sx={{ fontWeight: 600, mt: 1 }}>
                      {activePair.title}
                    </Typography>
                    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.85 }}>
                      {activePair.street ? <Chip size="small" variant="outlined" label={activePair.street} /> : null}
                      {activePair.action ? <Chip size="small" variant="outlined" label={activePair.action} /> : null}
                      {activePair.impactLabel ? <Chip size="small" color="secondary" variant="outlined" label={activePair.impactLabel} /> : null}
                      {activePair.confidence ? <Chip size="small" variant="outlined" label={activePair.confidence} /> : null}
                      {activePairSignalCount > 0 ? (
                        <Chip size="small" variant="outlined" label={`${copy.pairDetail} ${activePairSignalCount}`} />
                      ) : null}
                    </Stack>
                    {activePairMeta || activePair.gateResult ? (
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.35 }}>
                        {[activePairMeta || undefined, activePair.gateResult].filter(Boolean).join(" · ")}
                      </Typography>
                    ) : null}
                    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.85 }}>
                      {activePair.deltaEv ? <Chip size="small" color="secondary" variant="outlined" label={`${copy.delta} ${activePair.deltaEv}`} /> : null}
                      {activePair.actionShift ? <Chip size="small" variant="outlined" label={`${copy.action} ${activePair.actionShift}`} /> : null}
                      {activePair.confidenceShift ? <Chip size="small" variant="outlined" label={`${copy.confidence} ${activePair.confidenceShift}`} /> : null}
                    </Stack>
                    {activePair.note ? (
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.85 }}>
                        {activePair.note}
                      </Typography>
                    ) : null}
                    {pairwiseItems.length > 1 ? (
                      <Box sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.75 }}>
                          {copy.pairCompactNav}
                        </Typography>
                        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
                          {pairwiseItems.map((item, index) => (
                            <ButtonBase
                              key={`${item.id}-chip`}
                              onClick={() => setActivePairIndex(index)}
                              sx={(theme) => ({
                                minWidth: 0,
                                maxWidth: { xs: "100%", sm: 176 },
                                px: 1,
                                py: 0.65,
                                borderRadius: 999,
                                textAlign: "left",
                                border: `1px solid ${
                                  index === activePairIndex
                                    ? alpha(theme.palette.secondary.main, 0.42)
                                    : alpha(theme.palette.text.primary, 0.1)
                                }`,
                                backgroundColor:
                                  index === activePairIndex
                                    ? alpha(theme.palette.secondary.main, 0.12)
                                    : alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.03 : 0.018),
                              })}
                              aria-label={`${copy.pairLabel} ${index + 1} ${item.title}`}
                            >
                              <Stack spacing={0.15} sx={{ minWidth: 0 }}>
                                <Typography variant="caption" sx={{ fontWeight: 600 }} noWrap>
                                  {index + 1}. {item.street ?? item.action ?? item.title}
                                </Typography>
                                <Typography variant="caption" color="text.secondary" noWrap>
                                  {getPairPreview(item, copy)}
                                </Typography>
                              </Stack>
                            </ButtonBase>
                          ))}
                        </Stack>
                      </Box>
                    ) : null}
                    <Box sx={{ mt: 1.25 }}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.75 }}>
                          {copy.pairTable}
                        </Typography>
                        <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 1 }}>
                        <TextField
                          size="small"
                          label={copy.pairFilterSearch}
                          value={pairFilter}
                          onChange={(event) => setPairFilter(event.target.value)}
                          fullWidth
                        />
                        <TextField
                          select
                          size="small"
                          label={copy.pairFilterStreet}
                          value={pairStreetFilter}
                          onChange={(event) => setPairStreetFilter(event.target.value)}
                          sx={{ minWidth: { xs: "100%", md: 130 } }}
                        >
                          <MenuItem value="all">{copy.pairFilterAll}</MenuItem>
                          {pairStreetOptions.map((street) => (
                            <MenuItem key={street} value={street}>
                              {street}
                            </MenuItem>
                          ))}
                        </TextField>
                        <TextField
                          select
                          size="small"
                          label={copy.pairFilterPolicyPair}
                          value={pairPolicyFilter}
                          onChange={(event) => setPairPolicyFilter(event.target.value)}
                          sx={{ minWidth: { xs: "100%", md: 180 } }}
                        >
                          <MenuItem value="all">{copy.pairFilterAll}</MenuItem>
                          {pairPolicyOptions.map((policyPair) => (
                            <MenuItem key={policyPair} value={policyPair}>
                              {policyPair}
                            </MenuItem>
                          ))}
                        </TextField>
                        <TextField
                          select
                          size="small"
                          label={copy.pairFilterGate}
                          value={pairGateFilter}
                          onChange={(event) => setPairGateFilter(event.target.value)}
                          sx={{ minWidth: { xs: "100%", md: 170 } }}
                        >
                          <MenuItem value="all">{copy.pairFilterAll}</MenuItem>
                          {pairGateOptions.map((gate) => (
                            <MenuItem key={gate} value={gate}>
                              {gate}
                            </MenuItem>
                          ))}
                        </TextField>
                        <TextField
                          select
                          size="small"
                          label={copy.pairFilterSignal}
                          value={pairSignalFilter}
                          onChange={(event) => setPairSignalFilter(event.target.value as PairSignalFilter)}
                          sx={{ minWidth: { xs: "100%", md: 150 } }}
                        >
                          <MenuItem value="all">{copy.pairFilterAll}</MenuItem>
                          <MenuItem value="delta">{copy.delta}</MenuItem>
                          <MenuItem value="action">{copy.action}</MenuItem>
                          <MenuItem value="confidence">{copy.confidence}</MenuItem>
                        </TextField>
                        <TextField
                          size="small"
                          type="number"
                          label={copy.pairFilterDeltaMin}
                          value={pairDeltaMinFilter}
                          onChange={(event) => setPairDeltaMinFilter(event.target.value)}
                          inputProps={{ min: 0, step: 0.1 }}
                          sx={{ minWidth: { xs: "100%", md: 120 } }}
                        />
                        <TextField
                          select
                          size="small"
                          label={copy.pairFilterActionOnly}
                          value={pairActionShiftOnly}
                          onChange={(event) => setPairActionShiftOnly(event.target.value)}
                          sx={{ minWidth: { xs: "100%", md: 150 } }}
                        >
                          <MenuItem value="false">{copy.pairFilterAll}</MenuItem>
                          <MenuItem value="true">{copy.action}</MenuItem>
                        </TextField>
                        <TextField
                          select
                          size="small"
                          label={copy.pairSort}
                          value={pairSort}
                          onChange={(event) => handlePairSortChange(event.target.value as PairSortKey)}
                          sx={{ minWidth: { xs: "100%", md: 150 } }}
                        >
                          <MenuItem value="impact">{copy.pairSortImpact}</MenuItem>
                          <MenuItem value="delta">{copy.pairSortDelta}</MenuItem>
                          <MenuItem value="confidence">{copy.pairSortConfidence}</MenuItem>
                          <MenuItem value="policy">{copy.pairSortPolicy}</MenuItem>
                          <MenuItem value="recent">{copy.pairSortRecent}</MenuItem>
                          <MenuItem value="title">{copy.pairSortTitle}</MenuItem>
                        </TextField>
                      </Stack>
                      <Stack
                        direction={{ xs: "column", sm: "row" }}
                        spacing={1}
                        alignItems={{ xs: "stretch", sm: "center" }}
                        justifyContent="space-between"
                        sx={{ mb: 1 }}
                      >
                        <Box>
                          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                            {sortedFilteredPairwiseItems.length}/{pairwiseItems.length} {copy.pairFilterShown}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                            {copy.pairSortActive}: {getPairSortLabel(pairSort, copy)} ({getPairSortDirectionLabel(pairSortDirection, copy)})
                          </Typography>
                        </Box>
                        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "stretch", sm: "center" }}>
                          <TextField
                            select
                            size="small"
                            label={copy.pairExportScope}
                            value={pairExportScope}
                            onChange={(event) => setPairExportScope(event.target.value as PairExportScope)}
                            sx={{ minWidth: { xs: "100%", sm: 160 } }}
                          >
                            <MenuItem value="page">{copy.pairExportPage}</MenuItem>
                            <MenuItem value="filtered">{copy.pairExportFiltered}</MenuItem>
                          </TextField>
                          <TextField
                            select
                            size="small"
                            label={copy.pairRowsPerPage}
                            value={String(pairRowsPerPage)}
                            onChange={(event) => setPairRowsPerPage(Number(event.target.value))}
                            sx={{ minWidth: { xs: "100%", sm: 120 } }}
                          >
                            {PAIR_ROWS_PER_PAGE_OPTIONS.map((value) => (
                              <MenuItem key={value} value={String(value)}>
                                {value}
                              </MenuItem>
                            ))}
                          </TextField>
                          <Button
                            variant="outlined"
                            size="small"
                            onClick={handlePairExportCsv}
                            disabled={sortedFilteredPairwiseItems.length === 0}
                          >
                            {sortedFilteredPairwiseItems.length === 0 ? copy.pairExportEmpty : copy.pairExportCsv}
                          </Button>
                        </Stack>
                      </Stack>
                      <Box sx={{ mb: 1 }}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.75 }}>
                          {copy.pairVisibleColumns}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                          {copy.pairVisibleColumnsHint}
                        </Typography>
                        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                          {DEFAULT_PAIR_VISIBLE_COLUMNS.map((column) => {
                            const active = visiblePairColumns.includes(column);
                            return (
                              <Chip
                                key={column}
                                size="small"
                                label={getPairColumnLabel(column, copy)}
                                color={active ? "secondary" : undefined}
                                variant={active ? "filled" : "outlined"}
                                onClick={() => togglePairColumn(column)}
                              />
                            );
                          })}
                        </Stack>
                      </Box>
                      <TableContainer
                        sx={(theme) => ({
                          borderRadius: 2.5,
                          border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                          backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.028 : 0.012),
                        })}
                      >
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              <TableCell sortDirection={pairSort === "title" ? pairSortDirection : false}>
                                <TableSortLabel active={pairSort === "title"} direction={pairSort === "title" ? pairSortDirection : "asc"} onClick={() => handlePairHeaderSort("title")}>
                                  {copy.pairColSpot}
                                </TableSortLabel>
                              </TableCell>
                              {visiblePairColumns.includes("policy") ? (
                                <TableCell sortDirection={pairSort === "policy" ? pairSortDirection : false}>
                                  <TableSortLabel active={pairSort === "policy"} direction={pairSort === "policy" ? pairSortDirection : "asc"} onClick={() => handlePairHeaderSort("policy")}>
                                    {copy.pairColPolicy}
                                  </TableSortLabel>
                                </TableCell>
                              ) : null}
                              {visiblePairColumns.includes("signal") ? <TableCell>{copy.pairColSignal}</TableCell> : null}
                              {visiblePairColumns.includes("impact") ? (
                                <TableCell sortDirection={pairSort === "impact" ? pairSortDirection : false}>
                                  <TableSortLabel active={pairSort === "impact"} direction={pairSort === "impact" ? pairSortDirection : "desc"} onClick={() => handlePairHeaderSort("impact")}>
                                    {copy.pairColImpact}
                                  </TableSortLabel>
                                </TableCell>
                              ) : null}
                              {visiblePairColumns.includes("delta") ? (
                                <TableCell sortDirection={pairSort === "delta" ? pairSortDirection : false}>
                                  <TableSortLabel active={pairSort === "delta"} direction={pairSort === "delta" ? pairSortDirection : "desc"} onClick={() => handlePairHeaderSort("delta")}>
                                    {copy.pairColDelta}
                                  </TableSortLabel>
                                </TableCell>
                              ) : null}
                              {visiblePairColumns.includes("confidence") ? (
                                <TableCell sortDirection={pairSort === "confidence" ? pairSortDirection : false}>
                                  <TableSortLabel active={pairSort === "confidence"} direction={pairSort === "confidence" ? pairSortDirection : "desc"} onClick={() => handlePairHeaderSort("confidence")}>
                                    {copy.pairColConfidence}
                                  </TableSortLabel>
                                </TableCell>
                              ) : null}
                              {visiblePairColumns.includes("context") ? <TableCell>{copy.pairColContext}</TableCell> : null}
                              {visiblePairColumns.includes("recent") ? (
                                <TableCell sortDirection={pairSort === "recent" ? pairSortDirection : false}>
                                  <TableSortLabel active={pairSort === "recent"} direction={pairSort === "recent" ? pairSortDirection : "desc"} onClick={() => handlePairHeaderSort("recent")}>
                                    {copy.pairColUpdated}
                                  </TableSortLabel>
                                </TableCell>
                              ) : null}
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {paginatedFilteredPairwiseItems.length > 0 ? (
                              paginatedFilteredPairwiseItems.map((item) => {
                                const isActive = item.id === activePair?.id;
                                return (
                                  <TableRow
                                    key={`${item.id}-row`}
                                    hover
                                    selected={isActive}
                                    onClick={() => {
                                      const nextIndex = pairwiseItems.findIndex((candidate) => candidate.id === item.id);
                                      if (nextIndex >= 0) {
                                        setActivePairIndex(nextIndex);
                                      }
                                    }}
                                    sx={{ cursor: "pointer" }}
                                  >
                                    <TableCell sx={{ minWidth: 180 }}>
                                      <Typography variant="body2" sx={{ fontWeight: isActive ? 700 : 600 }}>
                                        {item.title}
                                      </Typography>
                                      <Typography variant="caption" color="text.secondary">
                                        {[item.street, item.action].filter(Boolean).join(" · ") || copy.noPairMeta}
                                      </Typography>
                                    </TableCell>
                                    {visiblePairColumns.includes("policy") ? (
                                      <TableCell>
                                        <Typography variant="body2">{getPairPolicyLabel(item)}</Typography>
                                        {getPairPolicyMeta(item) ? (
                                          <Typography variant="caption" color="text.secondary">
                                            {getPairPolicyMeta(item)}
                                          </Typography>
                                        ) : null}
                                      </TableCell>
                                    ) : null}
                                    {visiblePairColumns.includes("signal") ? (
                                      <TableCell>
                                        <Typography variant="body2">{getPairPrimarySignal(item, copy)}</Typography>
                                      </TableCell>
                                    ) : null}
                                    {visiblePairColumns.includes("impact") ? (
                                      <TableCell>
                                        <Typography variant="body2">{item.impactLabel ?? (item.impactScore != null ? item.impactScore.toFixed(1) : "-")}</Typography>
                                      </TableCell>
                                    ) : null}
                                    {visiblePairColumns.includes("delta") ? (
                                      <TableCell>
                                        <Typography variant="body2">{item.deltaEv ?? "-"}</Typography>
                                      </TableCell>
                                    ) : null}
                                    {visiblePairColumns.includes("confidence") ? (
                                      <TableCell>
                                        <Typography variant="body2">{item.confidence ?? item.confidenceShift ?? "-"}</Typography>
                                      </TableCell>
                                    ) : null}
                                    {visiblePairColumns.includes("context") ? (
                                      <TableCell>
                                        <Typography variant="body2">{getPairMeta(item) || item.gateResult || "-"}</Typography>
                                      </TableCell>
                                    ) : null}
                                    {visiblePairColumns.includes("recent") ? (
                                      <TableCell>
                                        <Typography variant="body2">{item.timestamp ?? "-"}</Typography>
                                      </TableCell>
                                    ) : null}
                                  </TableRow>
                                );
                              })
                            ) : (
                              <TableRow>
                                <TableCell colSpan={1 + visiblePairColumns.length}>
                                  <Typography variant="body2" color="text.secondary">
                                    {copy.pairNoRows}
                                  </Typography>
                                </TableCell>
                              </TableRow>
                            )}
                          </TableBody>
                        </Table>
                      </TableContainer>
                      <Stack
                        direction={{ xs: "column", sm: "row" }}
                        spacing={1}
                        alignItems={{ xs: "stretch", sm: "center" }}
                        justifyContent="space-between"
                        sx={{ mt: 1 }}
                      >
                        <Typography variant="caption" color="text.secondary">
                          {copy.pairPageRange}: {pairRangeStart}-{pairRangeEnd} / {sortedFilteredPairwiseItems.length}
                        </Typography>
                        <Stack direction="row" spacing={1} justifyContent="flex-end">
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => setPairPage((current) => Math.max(0, current - 1))}
                            disabled={currentPairPage === 0}
                          >
                            {copy.pairwise} -
                          </Button>
                          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
                            {currentPairPage + 1}/{pairPageCount}
                          </Typography>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => setPairPage((current) => Math.min(pairPageCount - 1, current + 1))}
                            disabled={currentPairPage >= pairPageCount - 1}
                          >
                            {copy.pairwise} +
                          </Button>
                        </Stack>
                      </Stack>
                    </Box>
                  </Box>
                ) : null}
                {comparisonItems.length > 0 ? (
                  <Box>
                    <ButtonBase
                      onClick={() => setExpanded((current) => ({ ...current, comparisons: !current.comparisons }))}
                      sx={{ width: "100%", borderRadius: 3, textAlign: "left" }}
                    >
                      <Stack
                        direction="row"
                        spacing={1}
                        alignItems="center"
                        justifyContent="space-between"
                        sx={(theme) => ({
                          width: "100%",
                          p: 1.25,
                          borderRadius: 3,
                          border: `1px solid ${alpha(theme.palette.secondary.main, 0.14)}`,
                          backgroundColor: alpha(theme.palette.secondary.main, 0.05),
                        })}
                      >
                        <Box>
                          <Typography variant="subtitle2">{copy.comparisons}</Typography>
                          <Typography variant="caption" color="text.secondary">
                            {getDrillDownLabel(comparisonItems.length, copy, expanded.comparisons)}
                          </Typography>
                        </Box>
                        <ExpandMoreRoundedIcon
                          fontSize="small"
                          sx={{
                            transform: expanded.comparisons ? "rotate(180deg)" : undefined,
                            transition: "transform 160ms ease",
                          }}
                        />
                      </Stack>
                    </ButtonBase>
                    <Collapse in={expanded.comparisons} timeout="auto" unmountOnExit>
                      <Stack spacing={1} sx={{ mt: 1 }}>
                        {comparisonItems.map((item) => (
                          <Box
                            key={item.id}
                            sx={(theme) => ({
                              p: 1.25,
                              borderRadius: 3,
                              border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                              backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.03 : 0.018),
                            })}
                          >
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                              {item.title}
                            </Typography>
                            {[item.canonicalSpot, item.gateResult].filter(Boolean).length > 0 ? (
                              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.35 }}>
                                {[item.canonicalSpot, item.gateResult].filter(Boolean).join(" · ")}
                              </Typography>
                            ) : null}
                            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.85 }}>
                              {item.deltaEv ? <Chip size="small" color="secondary" variant="outlined" label={`${copy.delta} ${item.deltaEv}`} /> : null}
                              {item.actionShift ? <Chip size="small" variant="outlined" label={`${copy.action} ${item.actionShift}`} /> : null}
                              {item.confidenceShift ? <Chip size="small" variant="outlined" label={`${copy.confidence} ${item.confidenceShift}`} /> : null}
                            </Stack>
                            {item.note ? (
                              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.85 }}>
                                {item.note}
                              </Typography>
                            ) : null}
                          </Box>
                        ))}
                      </Stack>
                    </Collapse>
                  </Box>
                ) : null}
                {highlightItems.length > 0 ? (
                  <Box>
                    <ButtonBase
                      onClick={() => setExpanded((current) => ({ ...current, highlights: !current.highlights }))}
                      sx={{ width: "100%", borderRadius: 3, textAlign: "left" }}
                    >
                      <Stack
                        direction="row"
                        spacing={1}
                        alignItems="center"
                        justifyContent="space-between"
                        sx={(theme) => ({
                          width: "100%",
                          p: 1.25,
                          mt: 0.5,
                          borderRadius: 3,
                          border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
                          backgroundColor: alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.03 : 0.018),
                        })}
                      >
                        <Box>
                          <Typography variant="subtitle2">{copy.highlights}</Typography>
                          <Typography variant="caption" color="text.secondary">
                            {getDrillDownLabel(highlightItems.length, copy, expanded.highlights)}
                          </Typography>
                        </Box>
                        <ExpandMoreRoundedIcon
                          fontSize="small"
                          sx={{
                            transform: expanded.highlights ? "rotate(180deg)" : undefined,
                            transition: "transform 160ms ease",
                          }}
                        />
                      </Stack>
                    </ButtonBase>
                    <Collapse in={expanded.highlights} timeout="auto" unmountOnExit>
                      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
                        {highlightItems.map((item) => (
                          <Chip
                            key={item.id}
                            size="small"
                            variant="outlined"
                            label={[item.title, item.canonicalSpot].filter(Boolean).join(" · ")}
                          />
                        ))}
                      </Stack>
                    </Collapse>
                  </Box>
                ) : null}
              </Stack>
            </Box>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

export default PolicyComparePanel;
