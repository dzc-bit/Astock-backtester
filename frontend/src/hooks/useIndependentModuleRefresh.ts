import { useEffect } from "react";

const INDEPENDENT_MODULE_REFRESH_MS = 120_000;
const INDEPENDENT_MODULE_RETRY_MS = 3_000;

export type IndependentModuleLoader = (isCancelled: () => boolean) => Promise<boolean>;

/**
 * Polls one independent page module: refresh on mount and every 120s while the
 * local data service is connected; a failed cycle retries after 3s.  Modules
 * keep their last successful payload when a refresh fails.
 */
export function useIndependentModuleRefresh(enabled: boolean, loader: IndependentModuleLoader): void {
  useEffect(() => {
    if (!enabled) {
      return;
    }
    let cancelled = false;
    let inFlight = false;
    let timer: number | undefined;

    const refresh = async () => {
      if (cancelled || inFlight) {
        return;
      }
      inFlight = true;
      let succeeded = false;
      try {
        succeeded = await loader(() => cancelled);
      } catch {
        succeeded = false;
      } finally {
        inFlight = false;
        if (!cancelled) {
          timer = window.setTimeout(
            refresh,
            succeeded ? INDEPENDENT_MODULE_REFRESH_MS : INDEPENDENT_MODULE_RETRY_MS
          );
        }
      }
    };

    void refresh();
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [enabled, loader]);
}
