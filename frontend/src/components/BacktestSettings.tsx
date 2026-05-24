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
    <section className="surface">
      <h2>Backtest Settings</h2>
      <div className="settings-grid">
        <label>
          Start date
          <input value={settings.start_date} onChange={(event) => update("start_date", event.target.value)} />
        </label>
        <label>
          End date
          <input value={settings.end_date} onChange={(event) => update("end_date", event.target.value)} />
        </label>
        <label>
          Initial capital
          <input
            aria-label="Initial capital"
            type="number"
            value={settings.initial_cash}
            onChange={(event) => update("initial_cash", Number(event.target.value))}
          />
        </label>
        <label>
          Fixed holding days
          <input
            type="number"
            value={settings.fixed_holding_days}
            onChange={(event) => update("fixed_holding_days", Number(event.target.value))}
          />
        </label>
        <label>
          Take profit
          <input
            type="number"
            step="0.01"
            value={settings.take_profit_pct ?? ""}
            onChange={(event) => update("take_profit_pct", event.target.value === "" ? null : Number(event.target.value))}
          />
        </label>
        <label>
          Stop loss
          <input
            type="number"
            step="0.01"
            value={settings.stop_loss_pct ?? ""}
            onChange={(event) => update("stop_loss_pct", event.target.value === "" ? null : Number(event.target.value))}
          />
        </label>
        <label>
          Max holdings
          <input
            type="number"
            value={settings.max_positions}
            onChange={(event) => update("max_positions", Number(event.target.value))}
          />
        </label>
        <label>
          Slippage
          <input
            type="number"
            step="0.0001"
            value={settings.slippage_rate}
            onChange={(event) => update("slippage_rate", Number(event.target.value))}
          />
        </label>
      </div>
    </section>
  );
}
