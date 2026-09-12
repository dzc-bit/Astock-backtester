import { invoke } from "@tauri-apps/api/core";
import { Bot, ExternalLink, Newspaper, RefreshCw } from "lucide-react";
import type { MouseEvent } from "react";
import type { AiDigestItem } from "../aiTypes";
import type { MarketNewsResponse } from "../types";
import { isTauriRuntime } from "../tauriRuntime";

type Props = {
  news: MarketNewsResponse | null;
  aiDigest?: AiDigestItem[];
  isLoading?: boolean;
  onRefresh?: () => void;
};

type NewsCard = {
  key: string;
  title: string;
  summary: string;
  source: string;
  publishedAt: string | null;
  tags: string[];
  url: string | null;
  sentiment: string;
  isAi: boolean;
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

async function openExternalUrl(url: string): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("open_external_url", { url });
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

function handleNewsLinkClick(event: MouseEvent<HTMLAnchorElement>, url: string): void {
  event.preventDefault();
  void openExternalUrl(url);
}

function buildCards(news: MarketNewsResponse | null, aiDigest: AiDigestItem[]): NewsCard[] {
  const aiCards: NewsCard[] = aiDigest.map((item) => ({
    key: `ai-${item.id}`,
    title: item.title,
    summary: item.summary,
    source: "ai-agent",
    publishedAt: item.created_at,
    tags: item.tags,
    url: null,
    sentiment: "neutral",
    isAi: true
  }));
  const newsCards: NewsCard[] = (news?.items ?? []).map((item, index) => ({
    key: `news-${index}-${item.title}`,
    title: item.title,
    summary: item.summary ?? "",
    source: item.source,
    publishedAt: item.published_at ?? null,
    tags: item.tags,
    url: item.url ?? null,
    sentiment: item.sentiment,
    isAi: false
  }));
  return [...aiCards, ...newsCards];
}

export function NewsPanel({ news, aiDigest, isLoading = false, onRefresh }: Props) {
  const cards = buildCards(news, aiDigest ?? []);
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

      {cards.length === 0 ? (
        <div className="empty-state">
          <strong>暂无资讯</strong>
          <span>本地服务连接后会展示市场新闻和事件线索。</span>
        </div>
      ) : (
        <div className="news-list">
          {cards.map((card) => (
            <article className={`news-item ${card.sentiment} ${card.isAi ? "ai-news-item" : ""}`} key={card.key}>
              <div className="news-icon" aria-hidden="true">
                {card.isAi ? <Bot size={17} /> : <Newspaper size={17} />}
              </div>
              <div className="news-copy">
                <div className="news-title-row">
                  <strong>{card.title}</strong>
                  <span>{formatTime(card.publishedAt)}</span>
                </div>
                {card.summary ? <p>{card.summary}</p> : null}
                <div className="news-meta">
                  <span>{card.source}</span>
                  {card.tags.map((tag) => (
                    <small key={tag}>{tag}</small>
                  ))}
                </div>
                {card.isAi ? <small className="ai-news-disclaimer">Agent 自动聚合 · 不构成投资建议</small> : null}
              </div>
              {card.url ? (
                <a
                  className="news-link"
                  href={card.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`打开${card.title}`}
                  onClick={(event) => handleNewsLinkClick(event, card.url as string)}
                >
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
