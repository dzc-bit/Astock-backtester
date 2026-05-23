export function BacktestSettings() {
  return (
    <section className="surface">
      <h2>Backtest Settings</h2>
      <div className="settings-grid">
        <label>Initial capital<input defaultValue="100000" /></label>
        <label>Fixed holding days<input defaultValue="5" /></label>
        <label>Take profit<input defaultValue="8%" /></label>
        <label>Stop loss<input defaultValue="-5%" /></label>
        <label>Max holdings<input defaultValue="10" /></label>
        <label>Slippage<input defaultValue="0.05%" /></label>
      </div>
    </section>
  );
}
