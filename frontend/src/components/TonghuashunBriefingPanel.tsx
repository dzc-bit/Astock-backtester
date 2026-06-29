import { invoke } from "@tauri-apps/api/core";
import { ExternalLink, FileText, Sunrise, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import type { MarketBriefingResponse, MarketBriefingTable } from "../types";

type Props = {
  fupan: MarketBriefingResponse | null;
  zaopan: MarketBriefingResponse | null;
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

function splitParagraphs(content: string | null | undefined): string[] {
  return (content ?? "")
    .split(/\n{2,}|\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isFullTextSection(title: string): boolean {
  return /^全文[:：]/.test(title.trim());
}

function compactText(value: string, maxLength = 120): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trimEnd()}...`;
}

const defaultGenericTableColumnLabels = ["项目", "内容", "说明", "备注", "来源", "时间"];
const themeGenericTableColumnLabels = ["题材", "异动原因", "影响", "备注", "来源", "时间"];
const companyGenericTableColumnLabels = ["公司/事项", "内容", "影响", "备注", "来源", "时间"];
const stockQuoteTableColumnLabels = ["个股", "涨幅", "现价", "备注", "来源", "时间"];

function isGenericTableColumn(column: string): boolean {
  return /^(字段|field|column|col)[\s_-]*[0-9０-９]+$/i.test(column.trim());
}

function genericTableColumnLabelsFor(tableTitle: string | null | undefined): string[] {
  const title = (tableTitle ?? "").trim();
  if (/个股|股票|热门个股|异动个股|涨幅榜|跌幅榜/.test(title)) {
    return stockQuoteTableColumnLabels;
  }
  if (/强势|方向|题材|板块|概念|热点/.test(title)) {
    return themeGenericTableColumnLabels;
  }
  if (/公司|事项|公告|停复牌/.test(title)) {
    return companyGenericTableColumnLabels;
  }
  return defaultGenericTableColumnLabels;
}

function cleanTableColumnLabel(column: string, index: number, tableTitle?: string | null): string {
  const trimmed = column.trim();
  const fallbackLabels = genericTableColumnLabelsFor(tableTitle);
  if (!trimmed) {
    return fallbackLabels[index] ?? `内容${index + 1}`;
  }
  if (isGenericTableColumn(trimmed)) {
    return fallbackLabels[index] ?? `内容${index + 1}`;
  }
  return trimmed;
}

function hasMeaningfulTableValue(value: string | null | undefined): boolean {
  const normalized = (value ?? "").trim();
  return normalized.length > 0 && normalized !== "--" && normalized !== "-";
}

function isTauriRuntime(): boolean {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

function isTonghuashunArticleUrl(url: string | null | undefined): url is string {
  const normalizedUrl = url?.trim();
  if (!normalizedUrl) {
    return false;
  }
  try {
    const parsed = new URL(normalizedUrl);
    return parsed.protocol === "https:" && parsed.hostname === "stock.10jqka.com.cn" && parsed.pathname.endsWith(".shtml");
  } catch {
    return false;
  }
}

function sourceArticleUrl(briefing: MarketBriefingResponse): string | null {
  const sourceUrl = briefing.source_url?.trim();
  return isTonghuashunArticleUrl(sourceUrl) ? sourceUrl : null;
}

async function openOriginalArticleUrl(url: string): Promise<void> {
  if (!isTonghuashunArticleUrl(url)) {
    return;
  }
  if (isTauriRuntime()) {
    await invoke("open_ths_original_url", { url });
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

function linkUrlOrSource(linkUrl: string | null | undefined, briefing: MarketBriefingResponse): string | null {
  const normalizedLink = linkUrl?.trim();
  if (normalizedLink) {
    return normalizedLink;
  }
  return sourceArticleUrl(briefing);
}

function BriefingCard({
  briefing,
  title,
  kicker,
  icon,
  accentClass,
  emptyText,
  onOpen,
  openButtonRef
}: {
  briefing: MarketBriefingResponse | null;
  title: string;
  kicker: string;
  icon: ReactNode;
  accentClass: string;
  emptyText: string;
  onOpen: () => void;
  openButtonRef: RefObject<HTMLButtonElement>;
}) {
  const originalUrl = briefing ? sourceArticleUrl(briefing) : null;
  return (
    <article className={`ths-briefing-card ${accentClass}`}>
      <div className="ths-briefing-icon" aria-hidden="true">
        {icon}
      </div>
      <div className="ths-briefing-copy">
        <div className="ths-briefing-head">
          <div>
            <span>{kicker}</span>
            <h3>{title}</h3>
          </div>
          <div className="ths-briefing-actions">
            {briefing ? (
              <>
                <button
                  className="secondary-button compact"
                  type="button"
                  onClick={onOpen}
                  aria-label={`查看${title}全文`}
                  ref={openButtonRef}
                >
                  查看全文
                </button>
                {originalUrl ? (
                  <button
                    className="icon-button ths-source-link"
                    type="button"
                    onClick={() => {
                      void openOriginalArticleUrl(originalUrl);
                    }}
                    aria-label={`打开同花顺原文：${title}`}
                    title="打开同花顺原文"
                  >
                    <ExternalLink size={15} aria-hidden="true" />
                  </button>
                ) : (
                  <button
                    className="icon-button ths-disabled-link"
                    type="button"
                    aria-label={`暂无${title}原文链接`}
                    title="暂无原文链接"
                    disabled
                  >
                    <ExternalLink size={15} aria-hidden="true" />
                  </button>
                )}
              </>
            ) : null}
          </div>
        </div>
        {briefing ? (
          <>
            <div className="ths-briefing-meta">
              <span>{briefing.source}</span>
              <span>{formatTime(briefing.updated_at)}</span>
              <span>{briefing.sections.length > 0 ? `${briefing.sections.length} 段全文` : "摘要"}</span>
            </div>
            <strong className="ths-briefing-brief">{compactText(briefing.summary)}</strong>
            <div className="ths-briefing-hints" aria-label={`${title}精要`}>
              <span>正文已收起</span>
              <span>点击查看可读完整内容</span>
            </div>
          </>
        ) : (
          <p className="ths-briefing-empty">{emptyText}</p>
        )}
      </div>
    </article>
  );
}

function BriefingTable({ table }: { table: MarketBriefingTable }) {
  const rawColumns =
    table.columns.length > 0
      ? table.columns
      : Array.from(new Set(table.rows.flatMap((row) => Object.keys(row))));
  const columns = rawColumns
    .map((column, index) => ({
      key: column,
      label: cleanTableColumnLabel(column, index, table.title),
      hasValue: table.rows.some((row) => hasMeaningfulTableValue(row[column]))
    }))
    .filter((column) => column.hasValue || !isGenericTableColumn(column.key));
  if (columns.length === 0 || table.rows.length === 0) {
    return null;
  }
  return (
    <div className="ths-briefing-table-wrap">
      {table.title ? <strong>{table.title}</strong> : null}
      <table className="ths-briefing-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={`${table.title ?? "table"}-${rowIndex}`}>
              {columns.map((column) => (
                <td key={column.key}>{row[column.key] ?? "--"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BriefingDialog({
  briefing,
  title,
  kicker,
  onClose
}: {
  briefing: MarketBriefingResponse;
  title: string;
  kicker: string;
  onClose: () => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const originalUrl = sourceArticleUrl(briefing);

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
      <section className="ths-briefing-modal" role="dialog" aria-modal="true" aria-label={`${title}全文`}>
        <div className="modal-head">
          <div>
            <span className="section-kicker">{kicker}</span>
            <h2>{title}全文</h2>
          </div>
          <button className="icon-button" type="button" aria-label={`关闭${title}全文`} onClick={onClose} ref={closeButtonRef}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="ths-briefing-modal-meta">
          <span>来源 {briefing.source}</span>
          <span>更新 {formatTime(briefing.updated_at)}</span>
          {originalUrl ? (
            <button
              className="secondary-button compact"
              type="button"
              onClick={() => {
                void openOriginalArticleUrl(originalUrl);
              }}
            >
              打开同花顺原文
              <ExternalLink size={14} aria-hidden="true" />
            </button>
          ) : (
            <button className="secondary-button compact" type="button" disabled aria-label="暂无同花顺原文链接">
              暂无原文链接
            </button>
          )}
        </div>
        <div className="ths-briefing-modal-body">
          <article className="ths-briefing-full-summary">
            <span>重点摘要</span>
            <p>{briefing.summary}</p>
          </article>
          {briefing.sections.length === 0 ? (
            <div className="empty-state">
              <strong>暂无更多正文</strong>
              <span>当前接口只返回了摘要，稍后可刷新或打开同花顺原文查看。</span>
            </div>
          ) : (
            <section className="ths-briefing-reader" aria-label="阅读全文">
              <div className="ths-briefing-reader-head">
                <span>阅读全文</span>
                <small>已按段落整理，向下滚动可读完整尾部。</small>
              </div>
              {briefing.sections.map((section, sectionIndex) => {
                const paragraphs = splitParagraphs(section.content);
                return (
                  <article
                    className={`ths-briefing-section${isFullTextSection(section.title) ? " full-text-section" : ""}`}
                    key={`${section.title}-${sectionIndex}`}
                  >
                    {isFullTextSection(section.title) ? (
                      <span className="ths-briefing-section-badge">抓取到的原文详情</span>
                    ) : null}
                    <h3>{section.title}</h3>
                    {paragraphs.length > 0 ? (
                      <div className="ths-briefing-paragraphs">
                        {paragraphs.map((paragraph, paragraphIndex) => (
                          <p key={`${section.title}-${paragraphIndex}`}>{paragraph}</p>
                        ))}
                      </div>
                    ) : null}
                    {section.links.length > 0 ? (
                      <div className="ths-briefing-link-list">
                        {section.links.map((link, linkIndex) => {
                          const href = linkUrlOrSource(link.url, briefing);
                          return href ? (
                            <a href={href} target="_blank" rel="noreferrer" key={`${link.title}-${linkIndex}`}>
                              {link.title}
                              <ExternalLink size={13} aria-hidden="true" />
                            </a>
                          ) : null;
                        })}
                      </div>
                    ) : null}
                    {section.tables.map((table, tableIndex) => (
                      <BriefingTable table={table} key={`${table.title ?? section.title}-${tableIndex}`} />
                    ))}
                  </article>
                );
              })}
            </section>
          )}
          {briefing.diagnostics.length > 0 ? (
            <ul className="risk-diagnostics" aria-label="同花顺总评诊断">
              {briefing.diagnostics.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </section>
    </div>
  );
}

export function TonghuashunBriefingPanel({ fupan, zaopan }: Props) {
  const [openKind, setOpenKind] = useState<MarketBriefingResponse["kind"] | null>(null);
  const fupanOpenButtonRef = useRef<HTMLButtonElement>(null);
  const zaopanOpenButtonRef = useRef<HTMLButtonElement>(null);
  const activeBriefing = openKind === "fupan" ? fupan : openKind === "zaopan" ? zaopan : null;
  const activeTitle = openKind === "fupan" ? "同花顺复盘总评" : "同花顺早盘总评";
  const activeKicker = openKind === "fupan" ? "收盘复盘" : "盘前观察";
  function closeBriefing() {
    const triggerRef = openKind === "fupan" ? fupanOpenButtonRef : zaopanOpenButtonRef;
    setOpenKind(null);
    triggerRef.current?.focus();
  }

  return (
    <>
      <section className="ths-briefing-panel" aria-label="同花顺复盘与早盘总评">
        <BriefingCard
          briefing={fupan}
          title="同花顺复盘总评"
          kicker="收盘复盘"
          icon={<FileText size={20} />}
          accentClass="fupan"
          emptyText="复盘总评暂未返回，行情框仍保留本地收盘评价。"
          onOpen={() => setOpenKind("fupan")}
          openButtonRef={fupanOpenButtonRef}
        />
        <BriefingCard
          briefing={zaopan}
          title="同花顺早盘总评"
          kicker="盘前观察"
          icon={<Sunrise size={20} />}
          accentClass="zaopan"
          emptyText="早盘总评暂未返回，资讯框仍会显示常规市场新闻。"
          onOpen={() => setOpenKind("zaopan")}
          openButtonRef={zaopanOpenButtonRef}
        />
      </section>
      {activeBriefing ? (
        <BriefingDialog briefing={activeBriefing} title={activeTitle} kicker={activeKicker} onClose={closeBriefing} />
      ) : null}
    </>
  );
}
