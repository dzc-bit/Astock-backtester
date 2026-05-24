import type { BacktestSettingsConfig } from "../types";

type Props = {
  settings: BacktestSettingsConfig;
  onSettingsChange: (settings: BacktestSettingsConfig) => void;
};

export function BacktestSettings({ settings, onSettingsChange }: Props) {
  const update = (key: keyof BacktestSettingsConfig, value: number | string | boolean | null) => {
    onSettingsChange({ ...settings, [key]: value });
  };

  return (
    <section className="surface settings-surface">
      <div className="section-title">
        <div>
          <span className="section-kicker">历史回滚参数</span>
          <h2>回测设置</h2>
        </div>
        <span className="status-pill compact">股票池：全A</span>
      </div>
      <div className="settings-grid">
        <label>
          开始日期
          <input value={settings.start_date} onChange={(event) => update("start_date", event.target.value)} />
        </label>
        <label>
          结束日期
          <input value={settings.end_date} onChange={(event) => update("end_date", event.target.value)} />
        </label>
        <label>
          初始资金
          <input
            aria-label="初始资金"
            type="number"
            value={settings.initial_cash}
            onChange={(event) => update("initial_cash", Number(event.target.value))}
          />
        </label>
        <label>
          固定持仓天数
          <input
            type="number"
            value={settings.fixed_holding_days}
            onChange={(event) => update("fixed_holding_days", Number(event.target.value))}
          />
        </label>
        <label>
          止盈比例
          <input
            type="number"
            step="0.01"
            value={settings.take_profit_pct ?? ""}
            onChange={(event) => update("take_profit_pct", event.target.value === "" ? null : Number(event.target.value))}
          />
        </label>
        <label>
          止损比例
          <input
            type="number"
            step="0.01"
            value={settings.stop_loss_pct ?? ""}
            onChange={(event) => update("stop_loss_pct", event.target.value === "" ? null : Number(event.target.value))}
          />
        </label>
        <label>
          最大持仓数
          <input
            type="number"
            value={settings.max_positions}
            onChange={(event) => update("max_positions", Number(event.target.value))}
          />
        </label>
        <label>
          滑点比例
          <input
            type="number"
            step="0.0001"
            value={settings.slippage_rate}
            onChange={(event) => update("slippage_rate", Number(event.target.value))}
          />
        </label>
      </div>
      <div className="settings-footnote">
        <span>执行假设：次日买入、保守处理同日止盈止损冲突、默认过滤 ST 与停牌样本。</span>
      </div>
    </section>
  );
}
