import { AlertTriangle, CheckCircle2, Compass, Eye, LineChart, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { MarketCommentaryResponse } from "../types";

type Props = {
  commentary: MarketCommentaryResponse | null;
  isLoading?: boolean;
};

function formatTime(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

const stanceLabel: Record<MarketCommentaryResponse["stance"], string> = {
  positive: "偏强",
  neutral: "中性",
  defensive: "防守"
};

const weightLabel: Record<MarketCommentaryResponse["drivers"][number]["weight"], string> = {
  high: "高",
  medium: "中",
  low: "低"
};

function compactText(value: string, maxLength = 112): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trimEnd()}...`;
}

function splitParagraphs(content: string): string[] {
  return content
    .split(/\n{2,}|\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function MarketCommentaryDialog({
  commentary,
  onClose
}: {
  commentary: MarketCommentaryResponse;
  onClose: () => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="modal-backdrop">
      <section className="commentary-modal" role="dialog" aria-modal="true" aria-label="行情评价全文">
        <div className="modal-head">
          <div>
            <span className="section-kicker">结构化复盘</span>
            <h2>行情评价全文</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭行情评价全文" onClick={onClose} ref={closeButtonRef}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="commentary-modal-meta">
          <span>来源 {commentary.source}</span>
          <span>交易日 {commentary.trade_date}</span>
          <span>更新 {formatTime(commentary.updated_at)}</span>
          <span>{stanceLabel[commentary.stance]}</span>
        </div>

        <div className="commentary-modal-body">
          <article className="commentary-full-section conclusion">
            <span>完整结论</span>
            {splitParagraphs(commentary.summary).map((paragraph, index) => (
              <p key={`summary-${index}`}>{paragraph}</p>
            ))}
          </article>

          <section className="commentary-full-section">
            <div className="commentary-reader-head">
              <span>主线全文</span>
              <small>主界面只展示精要，这里保留完整主线、风险和观察项。</small>
            </div>
            {commentary.drivers.length > 0 ? (
              <div className="commentary-full-list">
                {commentary.drivers.map((driver, index) => (
                  <article className={`commentary-full-card ${driver.weight}`} key={`${driver.title}-${index}`}>
                    <div className="commentary-mainline-title">
                      <strong>{driver.title}</strong>
                      <span>{weightLabel[driver.weight]}权重</span>
                    </div>
                    {splitParagraphs(driver.detail).map((paragraph, paragraphIndex) => (
                      <p key={`${driver.title}-${paragraphIndex}`}>{paragraph}</p>
                    ))}
                  </article>
                ))}
              </div>
            ) : (
              <p className="commentary-muted">今日没有形成足够清晰的主线。</p>
            )}
          </section>

          <section className="commentary-full-section risks">
            <strong>
              <AlertTriangle size={15} aria-hidden="true" />
              风险提示
            </strong>
            {commentary.risks.length > 0 ? (
              <ul>
                {commentary.risks.map((risk, index) => (
                  <li key={`risk-${index}`}>{risk}</li>
                ))}
              </ul>
            ) : (
              <span>暂无额外风险提示。</span>
            )}
          </section>

          <section className="commentary-full-section watch">
            <strong>
              <Eye size={15} aria-hidden="true" />
              明日观察
            </strong>
            {commentary.next_watch.length > 0 ? (
              <ul>
                {commentary.next_watch.map((item, index) => (
                  <li key={`watch-${index}`}>{item}</li>
                ))}
              </ul>
            ) : (
              <span>继续观察量能、红绿家数和主线承接。</span>
            )}
          </section>

          {commentary.diagnostics.length > 0 ? (
            <ul className="risk-diagnostics" aria-label="行情评价诊断">
              {commentary.diagnostics.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </section>
    </div>
  );
}

export function MarketCommentaryPanel({ commentary, isLoading = false }: Props) {
  const [isFullTextOpen, setIsFullTextOpen] = useState(false);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const hasCompleteRealtimeContext = commentary?.diagnostics.some((message) => message.includes("实时盘面数据完整")) ?? false;
  const isRealtimeContextIncomplete =
    commentary != null &&
    !hasCompleteRealtimeContext &&
    (commentary.summary.includes("实时盘面暂不可用") || commentary.summary.includes("新闻线索候选") || commentary.diagnostics.length > 0);
  const incompleteContextReason = commentary?.diagnostics[0] ?? "实时盘面数据不完整，当前结论仅作线索参考。";

  function closeFullText() {
    setIsFullTextOpen(false);
    openButtonRef.current?.focus();
  }

  return (
    <>
      <section className="surface market-commentary-panel" aria-label="行情评价">
        <div className="section-title">
          <div>
            <span className="section-kicker">结构化复盘</span>
            <h2>行情评价</h2>
          </div>
          <div className="commentary-actions">
            <span className={`status-pill compact commentary-tone ${commentary?.stance ?? "loading"}`}>
              <Compass size={15} aria-hidden="true" />
              {isLoading ? "生成中" : commentary ? stanceLabel[commentary.stance] : "待连接"}
            </span>
            {commentary ? (
              <button
                className="secondary-button compact"
                type="button"
                aria-label="查看行情评价全文"
                onClick={() => setIsFullTextOpen(true)}
                ref={openButtonRef}
              >
                查看全文
              </button>
            ) : null}
          </div>
        </div>

        {!commentary ? (
          <div className="empty-state">
            <strong>{isLoading ? "正在生成行情评价" : "暂无行情评价"}</strong>
            <span>后端 `/market/commentary` 返回后，会按结论、主线、风险和明日观察展示。</span>
          </div>
        ) : (
          <>
            <article className="commentary-conclusion">
              <div>
                <CheckCircle2 size={18} aria-hidden="true" />
                <span>结论</span>
              </div>
              <p>{compactText(commentary.summary, 124)}</p>
            </article>

            {isRealtimeContextIncomplete ? (
              <div className="commentary-context-warning">
                <strong>依据不完整</strong>
                <span>{compactText(incompleteContextReason, 88)}</span>
              </div>
            ) : null}

            <div className="commentary-grid">
              <section className="commentary-block mainlines-block">
                <div className="commentary-block-title">
                  <LineChart size={17} aria-hidden="true" />
                  <h3>主线</h3>
                </div>
                {commentary.drivers.length > 0 ? (
                  commentary.drivers.slice(0, 1).map((driver) => (
                    <article className={`commentary-mainline ${driver.weight}`} key={driver.title}>
                      <div className="commentary-mainline-title">
                        <strong>{driver.title}</strong>
                        <span>{weightLabel[driver.weight]}权重</span>
                      </div>
                      <p>{compactText(driver.detail, 96)}</p>
                    </article>
                  ))
                ) : (
                  <p className="commentary-muted">今日没有形成足够清晰的主线。</p>
                )}
              </section>

              <section className="commentary-block risks-block">
                <div className="commentary-block-title">
                  <AlertTriangle size={17} aria-hidden="true" />
                  <h3>风险</h3>
                </div>
                {commentary.risks.length > 0 ? (
                  commentary.risks.slice(0, 1).map((risk, index) => (
                    <article className="commentary-risk medium" key={`risk-${index}`}>
                      <strong>风险提示</strong>
                      <p>{compactText(risk, 76)}</p>
                    </article>
                  ))
                ) : (
                  <p className="commentary-muted">暂无额外风险提示。</p>
                )}
              </section>

              <section className="commentary-block watch-block">
                <div className="commentary-block-title">
                  <Eye size={17} aria-hidden="true" />
                  <h3>明日观察</h3>
                </div>
                {commentary.next_watch.length > 0 ? (
                  <ul className="watchpoint-list">
                    {commentary.next_watch.slice(0, 2).map((item, index) => (
                      <li key={`watch-${index}`}>{compactText(item, 72)}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="commentary-muted">继续观察量能、红绿家数和主线承接。</p>
                )}
              </section>
            </div>

            <p className="commentary-footnote">
              来源 {commentary.source} / 交易日 {commentary.trade_date} / 更新 {formatTime(commentary.updated_at)}
            </p>
          </>
        )}
      </section>
      {commentary && isFullTextOpen ? (
        <MarketCommentaryDialog commentary={commentary} onClose={closeFullText} />
      ) : null}
    </>
  );
}
