import type { ReactNode } from "react";
import type { SxProps, Theme } from "@mui/material/styles";
import type { ReplayPolicyCompareAggregate } from "../types";

export type ReplayAnalyticsState = "idle" | "loading" | "ready" | "degraded" | "offline" | "error";

export type ReplaySignalTone = "neutral" | "info" | "success" | "warning" | "error";

export interface SessionKpi {
  label: string;
  value: string;
  helper?: string;
  delta?: string;
  tone?: ReplaySignalTone;
  icon?: ReactNode;
}

export interface SessionLeakGroup {
  id?: string;
  label: string;
  count?: number;
  detail?: string;
  tone?: ReplaySignalTone;
  tags?: string[];
}

export interface SessionOverviewPanelProps {
  title?: string;
  subtitle?: string;
  locale?: "en" | "fr";
  state?: ReplayAnalyticsState;
  sessionName?: string;
  sessionMeta?: string;
  summary?: string;
  sessionStats?: SessionKpi[];
  trendKpis?: SessionKpi[];
  leakGroups?: SessionLeakGroup[];
  headlineTags?: string[];
  emptyMessage?: string;
  onReviewLatest?: () => void;
  onOpenTimeline?: () => void;
  onExport?: () => void;
  sx?: SxProps<Theme>;
}

export interface ReplayTimelineSpot {
  id: string;
  title: string;
  street?: string;
  timestamp?: string;
  policyPairKey?: string;
  policyPairLabel?: string;
  action?: string;
  result?: string;
  heroEv?: string;
  exploitability?: string;
  confidence?: string;
  canonicalSpot?: string;
  gateResult?: string;
  runtimeMetrics?: string[];
  incidents?: string[];
  decisionTrace?: string[];
  tags?: string[];
  note?: string;
  rlDiffSummary?: {
    label: string;
    deltaEv?: string;
    actionShift?: string;
    confidenceShift?: string;
  };
  impactScore?: number;
  impactLabel?: string;
  reviewed?: boolean;
  selected?: boolean;
  spotDetails?: Array<{ label: string; value: string }>;
  gateDetails?: Array<{ label: string; value: string }>;
  traceDetails?: Array<{ label: string; value: string }>;
}

export type PolicyCompareAggregate = ReplayPolicyCompareAggregate;

export interface ReplayTimelinePanelProps {
  title?: string;
  subtitle?: string;
  locale?: "en" | "fr";
  state?: ReplayAnalyticsState;
  items?: ReplayTimelineSpot[];
  selectedSpotId?: string;
  emptyMessage?: string;
  loadingMessage?: string;
  sortedByImpact?: boolean;
  impactSummary?: string;
  onSelectSpot?: (spotId: string) => void;
  onJumpToLatest?: () => void;
  onRefresh?: () => void;
  sx?: SxProps<Theme>;
}
