import axios from "axios";
import { useEffect, useState } from "react";

export const API_URL =
  import.meta.env.VITE_REACT_APP_API_URL || "http://127.0.0.1:8005";

export interface DlLinkState {
  /** Resolved download URL, or null when unavailable. */
  link: string | null;
  loading: boolean;
  /** True when the runtime API could not provide a download link. */
  error: boolean;
}

/**
 * Endpoint (relative to API_URL) able to provide the legacy download link.
 *
 * The local runtime API (src/api/server.py: /runtime-snapshot, /runtime-history,
 * /bot-cockpit/payload, /debug/*) exposes no equivalent of the legacy
 * `/get_internal` endpoint, so there is nothing to fetch in local mode.
 * When null, useDlLink skips the network request entirely and reports the
 * link as unavailable instead of firing a request that can only fail.
 */
const DL_LINK_ENDPOINT: string | null = null;

export const useDlLink = (): DlLinkState => {
  const [state, setState] = useState<DlLinkState>(() => ({
    link: null,
    loading: DL_LINK_ENDPOINT !== null,
    error: false,
  }));

  useEffect(() => {
    if (DL_LINK_ENDPOINT === null) {
      // No matching local endpoint: go straight to the "unavailable" state.
      return;
    }
    let cancelled = false;

    const fetchDlLink = async () => {
      try {
        const response = await axios.post(
          `${API_URL}${DL_LINK_ENDPOINT}`,
          null,
          { timeout: 5000 }
        );
        const link: string | null = response.data?.[0]?.dl ?? null;
        if (!cancelled) {
          setState({ link, loading: false, error: link === null });
        }
      } catch (error) {
        console.error("Error fetching dl link:", error);
        if (!cancelled) {
          setState({ link: null, loading: false, error: true });
        }
      }
    };

    fetchDlLink();
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
};
