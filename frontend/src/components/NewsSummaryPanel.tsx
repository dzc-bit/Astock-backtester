import { AlertCircle, Newspaper, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { NewsSummaryResponse } from "../types";

type Props = {
  summary: NewsSummaryResponse | null;
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

function NewsSummaryDialog({
  summary,
  onClose
}: {
  summary: NewsSummaryResponse;
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
      <section className="news-summary-modal" role="dialog" aria-modal="true" aria-label="新闻汇总全文">
        <div className="modal-head">
          <div>
            <span className="section-kicker">主题归纳</span>
            <h2>新闻汇总全文</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭新闻汇总全文" onClick={onClose} ref={closeButtonRef}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="news-summary-modal-meta">
          <span>来源 {summary.source}</span>
          <span>更新 {formatTime(summary.updated_at)}</span>
          <span>{summary.item_count} 条新闻</span>
        </div>
        <div className="news-summary-modal-body">
          {summary.highlights.length > 0 ? (
            <section className="news-summary-full-section highlight">
              <span className="news-summary-full-kicker">今日精要</span>
              <ul>
                {summary.highlights.map((highlight) => (
                  <li key={highlight}>{highlight}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="news-summary-full-section">
            <div className="news-summary-reader-head">
              <span>主题全文</span>
              <small>主界面只保留精要，这里展示完整摘要、全部要点和风险。</small>
            </div>
            <div className="news-summary-full-topics">
              {summary.themes.map((theme) => (
                <article className={`news-summary-full-topic ${theme.sentiment}`} key={theme.title}>
                  <div className="news-summary-topic-head">
                    <div>
                      <span>{theme.source_count} 个来源 / {theme.sentiment}</span>
                      <h3>{theme.title}</h3>
                    </div>
                    <Sparkles size={18} aria-hidden="true" />
                  </div>
                  <div className="news-summary-paragraphs">
                    {splitParagraphs(theme.summary).map((paragraph, index) => (
                      <p key={`${theme.title}-${index}`}>{paragraph}</p>
                    ))}
                  </div>
                  {theme.headlines.length > 0 ? (
                    <div className="news-summary-full-list">
                      <strong>全部要点</strong>
                      <ul>
                        {theme.headlines.map((point) => (
                          <li key={point}>{point}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </section>

          <section className="news-summary-full-section risks">
            <strong>
              <AlertCircle size={15} aria-hidden="true" />
              风险提示
            </strong>
            {summary.risks.length > 0 ? (
              <ul>
                {summary.risks.map((risk) => (
                  <li key={risk}>{risk}</li>
                ))}
              </ul>
            ) : (
              <span>暂无集中风险。</span>
            )}
          </section>

          {summary.diagnostics.length > 0 ? (
            <ul className="risk-diagnostics" aria-label="新闻汇总诊断">
              {summary.diagnostics.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </section>
    </div>
  );
}

export function NewsSummaryPanel({ summary, isLoading = false }: Props) {
  const [isFullTextOpen, setIsFullTextOpen] = useState(false);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const themes = summary?.themes ?? [];

  function closeFullText() {
    setIsFullTextOpen(false);
    openButtonRef.current?.focus();
  }

  return (
    <>
      <section className="surface news-summary-panel" aria-label="新闻汇总">
        <div className="section-title">
          <div>
            <span className="section-kicker">主题归纳</span>
            <h2>新闻汇总</h2>
          </div>
          <div className="news-summary-actions">
            <span className="status-pill compact news-source-count">
              <Newspaper size={15} aria-hidden="true" />
              {summary ? `${summary.item_count} 条新闻` : isLoading ? "汇总中" : "待连接"}
            </span>
            {summary ? (
              <button
                className="secondary-button compact"
                type="button"
                aria-label="查看新闻汇总全文"
                onClick={() => setIsFullTextOpen(true)}
                ref={openButtonRef}
              >
                查看全文
              </button>
            ) : null}
          </div>
        </div>

        {themes.length === 0 ? (
          <div className="empty-state">
            <strong>{isLoading ? "正在汇总今日新闻" : "暂无新闻汇总"}</strong>
            <span>后端 `/market/news-summary` 返回后，会展示主题、要点、风险和来源条数。</span>
          </div>
        ) : (
          <div className="news-summary-list">
            {themes.map((theme) => (
              <article className={`news-summary-topic ${theme.sentiment}`} key={theme.title}>
                <div className="news-summary-topic-head">
                  <div>
                    <span>{theme.source_count} 个来源 / {theme.sentiment}</span>
                    <h3>{theme.title}</h3>
                  </div>
                  <Sparkles size={18} aria-hidden="true" />
                </div>
                <p className="news-summary-brief">{compactText(theme.summary)}</p>
                <div className="news-summary-teasers" aria-label={`${theme.title}精要`}>
                  {theme.headlines.length > 0 ? (
                    <>
                      {theme.headlines.slice(0, 2).map((point) => (
                        <span className="news-summary-chip" key={point}>
                          {compactText(point, 34)}
                        </span>
                      ))}
                      {theme.headlines.length > 2 ? (
                        <span className="news-summary-chip muted">+{theme.headlines.length - 2} 条要点</span>
                      ) : null}
                    </>
                  ) : (
                    <span className="news-summary-chip muted">暂无明确要点</span>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}

        {summary ? (
          <p className="news-summary-footnote">
            来源 {summary.source} / 更新 {formatTime(summary.updated_at)}
          </p>
        ) : null}
      </section>
      {summary && isFullTextOpen ? (
        <NewsSummaryDialog summary={summary} onClose={closeFullText} />
      ) : null}
    </>
  );
}
