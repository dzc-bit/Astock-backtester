import { ExternalLink, Newspaper, RefreshCw } from "lucide-react";
import type { MarketNewsResponse } from "../types";

type Props = {
  news: MarketNewsResponse | null;
  isLoading?: boolean;
  onRefresh?: () => void;
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

export function NewsPanel({ news, isLoading = false, onRefresh }: Props) {
  const items = news?.items ?? [];
  return (
    <section className="surface news-panel" aria-label="资讯与事件">
      <div className="section-title">
        <div>
          <span className="section-kicker">市场资讯</span>
          <h2>资讯与事件</h2>
        </div>
        <button className="secondary-button" type="button" onClick={onRefresh} disabled={isLoading || !onRefresh}>
          <RefreshCw size={16} aria-hidden="true" />
          {isLoading ? "刷新中" : "刷新资讯"}
        </button>
      </div>

      {items.length === 0 ? (
        <div className="empty-state">
          <strong>暂无资讯</strong>
          <span>本地服务连接后会展示市场新闻和事件线索。</span>
        </div>
      ) : (
        <div className="news-list">
          {items.slice(0, 18).map((item, index) => (
            <article className={`news-item ${item.sentiment}`} key={`${item.title}-${index}`}>
              <div className="news-icon" aria-hidden="true">
                <Newspaper size={17} />
              </div>
              <div className="news-copy">
                <div className="news-title-row">
                  <strong>{item.title}</strong>
                  <span>{formatTime(item.published_at)}</span>
                </div>
                {item.summary ? <p>{item.summary}</p> : null}
                <div className="news-meta">
                  <span>{item.source}</span>
                  {item.tags.map((tag) => (
                    <small key={tag}>{tag}</small>
                  ))}
                </div>
              </div>
              {item.url ? (
                <a className="news-link" href={item.url} target="_blank" rel="noreferrer" aria-label={`打开${item.title}`}>
                  <ExternalLink size={15} aria-hidden="true" />
                </a>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
