import { AlertTriangle, CheckCircle2, Compass, Eye, LineChart } from "lucide-react";
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

export function MarketCommentaryPanel({ commentary, isLoading = false }: Props) {
  return (
    <section className="surface market-commentary-panel" aria-label="行情评价">
      <div className="section-title">
        <div>
          <span className="section-kicker">结构化复盘</span>
          <h2>行情评价</h2>
        </div>
        <span className={`status-pill compact commentary-tone ${commentary?.stance ?? "loading"}`}>
          <Compass size={15} aria-hidden="true" />
          {isLoading ? "生成中" : commentary ? stanceLabel[commentary.stance] : "待连接"}
        </span>
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
            <p>{commentary.summary}</p>
          </article>

          <div className="commentary-grid">
            <section className="commentary-block mainlines-block">
              <div className="commentary-block-title">
                <LineChart size={17} aria-hidden="true" />
                <h3>主线</h3>
              </div>
              {commentary.drivers.length > 0 ? (
                commentary.drivers.map((driver) => (
                  <article className={`commentary-mainline ${driver.weight}`} key={driver.title}>
                    <div className="commentary-mainline-title">
                      <strong>{driver.title}</strong>
                      <span>{weightLabel[driver.weight]}权重</span>
                    </div>
                    <p>{driver.detail}</p>
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
                commentary.risks.map((risk) => (
                  <article className="commentary-risk medium" key={risk}>
                    <strong>风险提示</strong>
                    <p>{risk}</p>
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
                  {commentary.next_watch.map((item) => (
                    <li key={item}>{item}</li>
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
  );
}
