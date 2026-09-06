import { useEffect } from "react";
import { loadRealtimeMarketSnapshot, loadRealtimeMarketSnapshotStream } from "../api";
import type { DataServiceStatus, MarketRefreshMeta, RealtimeMarketSnapshot } from "../types";
import {
  detectMarketSessionPhase,
  nextMarketRefreshMeta,
  refreshIntervalForMarketResult,
  refreshIntervalForPhase
} from "../marketRefresh";

type UseMarketPollingArgs = {
  dataService: DataServiceStatus | null;
  marketSnapshot: RealtimeMarketSnapshot | null;
  setIsLoadingMarket: (loading: boolean) => void;
  setMarketSnapshot: (update: (current: RealtimeMarketSnapshot | null) => RealtimeMarketSnapshot | null) => void;
  setMarketRefreshMeta: (update: (current: MarketRefreshMeta) => MarketRefreshMeta) => void;
};

/**
 * Streams the realtime market snapshot on a phase-aware refresh loop.
 *
 * The effect intentionally depends only on `dataService`: the snapshot known
 * at loop start decides whether the first fetch renders as a full load, and
 * the loop reschedules itself with the interval computed from each result.
 */
export function useMarketPolling({
  dataService,
  marketSnapshot,
  setIsLoadingMarket,
  setMarketSnapshot,
  setMarketRefreshMeta
}: UseMarketPollingArgs): void {
  useEffect(() => {
    if (!dataService) {
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    let activeRequest: AbortController | undefined;
    let hasCompleteSnapshot = marketSnapshot !== null && marketSnapshot.status !== "unavailable";
    const refreshMarket = async () => {
      const requestController = new AbortController();
      activeRequest = requestController;
      const phase = detectMarketSessionPhase();
      let nextRefreshMs = refreshIntervalForPhase(phase);
      const isInitialLoad = !hasCompleteSnapshot;
      if (isInitialLoad) {
        setIsLoadingMarket(true);
        setMarketRefreshMeta((current) => ({
          ...current,
          phase,
          status: "refreshing",
          message: "刷新中",
          next_refresh_ms: refreshIntervalForPhase(phase)
        }));
      }
      try {
        const applySnapshot = (snapshot: RealtimeMarketSnapshot, isPartial = false) => {
          if (cancelled || (isPartial && hasCompleteSnapshot)) {
            return;
          }
          if (!isPartial && snapshot.status !== "unavailable") {
            hasCompleteSnapshot = true;
          }
          setMarketSnapshot((current) => (snapshot.status === "unavailable" && current ? current : snapshot));
          const nextPhase = snapshot.market_phase ?? phase;
          nextRefreshMs = refreshIntervalForMarketResult(
            nextPhase,
            snapshot.diagnostics,
            snapshot.status === "unavailable"
          );
          setMarketRefreshMeta((current) => nextMarketRefreshMeta(current, snapshot, phase, isPartial));
        };
        const snapshot = await loadRealtimeMarketSnapshotStream(dataService.base_url, {
          onSnapshot: (partial) => applySnapshot(partial, true)
        }, { signal: requestController.signal });
        applySnapshot(snapshot);
      } catch (caught) {
        if (cancelled || requestController.signal.aborted) {
          return;
        }
        try {
          const snapshot = await loadRealtimeMarketSnapshot(dataService.base_url);
          if (!cancelled) {
            if (snapshot.status !== "unavailable") {
              hasCompleteSnapshot = true;
            }
            setMarketSnapshot((current) => (snapshot.status === "unavailable" && current ? current : snapshot));
            const nextPhase = snapshot.market_phase ?? phase;
            nextRefreshMs = refreshIntervalForMarketResult(
              nextPhase,
              snapshot.diagnostics,
              snapshot.status === "unavailable"
            );
            setMarketRefreshMeta((current) => nextMarketRefreshMeta(current, snapshot, phase));
          }
        } catch (fallbackCaught) {
          if (!cancelled) {
            const reason = fallbackCaught instanceof Error
              ? fallbackCaught.message
              : caught instanceof Error
                ? caught.message
                : "请求失败";
            setMarketRefreshMeta((current) => ({
              phase,
              status: current.last_success_at ? "using_last_success" : "unavailable",
              message: current.last_success_at ? "实时接口暂不可用，使用最近数据" : "实时接口暂不可用",
              last_success_at: current.last_success_at ?? null,
              last_error: reason,
              next_refresh_ms: refreshIntervalForPhase(phase, true)
            }));
            nextRefreshMs = refreshIntervalForPhase(phase, true);
          }
        }
      } finally {
        if (activeRequest === requestController) {
          activeRequest = undefined;
        }
        if (!cancelled) {
          if (isInitialLoad) {
            setIsLoadingMarket(false);
          }
          timer = window.setTimeout(refreshMarket, nextRefreshMs);
        }
      }
    };
    void refreshMarket();
    return () => {
      cancelled = true;
      activeRequest?.abort();
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loop must not restart when a snapshot arrives
  }, [dataService]);
}
