import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { aiInsightOneshot } from "../aiApi";
import type { AiInsightScene } from "../aiTypes";

type Props = {
  baseUrl: string | null;
  scene: AiInsightScene;
  context: Record<string, unknown>;
  label: string;
};

/**
 * One-line AI commentary. Fetches on mount (or when `trigger` changes) and
 * fails silent: nothing renders while loading or when AI is unconfigured.
 * Remount via `key` to refresh after the underlying data changes.
 */
export function AiOneShotLine({ baseUrl, scene, context, label }: Props) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    if (!baseUrl) {
      return;
    }
    let cancelled = false;
    aiInsightOneshot(baseUrl, scene, context)
      .then((result) => {
        if (!cancelled && result) {
          setText(result);
        }
      })
      .catch(() => {
        // 失败静默：AI 未配置或上游异常时不显示点评行。
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl, scene, label]);

  if (!text) {
    return null;
  }
  return (
    <div className="ai-oneshot-line" aria-label={label}>
      <Sparkles size={14} aria-hidden="true" />
      <span>{text}</span>
    </div>
  );
}
