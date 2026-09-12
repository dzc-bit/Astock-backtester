import { useEffect, useRef } from "react";
import { openAiEventStream } from "../aiApi";
import type { AiEventStreamEvent, AiInsight } from "../aiTypes";

type Options = {
  baseUrl: string | null;
  enabled: boolean;
  onInsight?: (insight: AiInsight) => void;
  onDataFresh?: (module: string) => void;
};

const RECONNECT_DELAY_MS = 3_000;

/**
 * Subscribes to /ai/events/stream while the local data service is connected.
 * `data_fresh` lets the page refresh modules immediately instead of waiting for
 * the next polling cycle; `insight` carries AI-generated briefs. Reconnects
 * automatically with a fixed delay; disconnects on unmount/disable.
 */
export function useAiEventStream({ baseUrl, enabled, onInsight, onDataFresh }: Options): void {
  const handlersRef = useRef({ onInsight, onDataFresh });
  handlersRef.current = { onInsight, onDataFresh };

  useEffect(() => {
    if (!enabled || !baseUrl) {
      return;
    }
    let cancelled = false;
    let controller: AbortController | null = null;
    let reconnectTimer: number | undefined;

    const connect = async () => {
      while (!cancelled) {
        controller = new AbortController();
        try {
          await openAiEventStream(
            baseUrl,
            (event: AiEventStreamEvent) => {
              if (event.type === "insight" && event.insight) {
                handlersRef.current.onInsight?.(event.insight);
              } else if (event.type === "data_fresh" && event.module) {
                handlersRef.current.onDataFresh?.(event.module);
              }
            },
            { signal: controller.signal }
          );
        } catch {
          // stream failed (service restart / idle timeout) — fall through to reconnect
        }
        if (cancelled) {
          return;
        }
        await new Promise((resolve) => {
          reconnectTimer = window.setTimeout(resolve, RECONNECT_DELAY_MS);
        });
      }
    };

    void connect();
    return () => {
      cancelled = true;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      controller?.abort();
    };
  }, [baseUrl, enabled]);
}
