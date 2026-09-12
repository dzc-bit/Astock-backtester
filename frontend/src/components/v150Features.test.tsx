import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { AiConditionParseResult } from "../aiTypes";
import { defaultSettings, defaultStrategy } from "../strategyDefaults";
import type { BacktestResult, OptimizeSummary } from "../types";
import { buildBacktestReportHtml } from "../reportHtml";
import { AiOneShotLine } from "./AiOneShotLine";
import { StrategyOptimizer } from "./StrategyOptimizer";
import { StrategyWorkbench } from "./StrategyWorkbench";

const aiApi = vi.hoisted(() => ({
  aiInsightOneshot: vi.fn(),
  runAiOptimizeStream: vi.fn()
}));

vi.mock("../aiApi", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...aiApi
}));

const parseResult: AiConditionParseResult = {
  entry: [
    {
      id: "parse-entry-0",
      condition_id: "volume_ratio_between",
      enabled: true,
      params: { window: 2, min: 1.2, max: 2.5 },
      data_lag_days: 0,
      expression: "量比2日介于1.2到2.5"
    },
    {
      id: "parse-entry-1",
      condition_id: "capital_flow_n_day_sum_at_least",
      enabled: true,
      params: { window: 5, min: 3_000_000 },
      data_lag_days: 0,
      expression: "近5日主力净流入大于300万"
    }
  ],
  exit: [
    {
      id: "parse-exit-0",
      condition_id: "close_below_ma",
      enabled: true,
      params: { window: 20 },
      data_lag_days: 0,
      expression: "收盘价跌破20日均线"
    }
  ],
  approximations: ["『放量』→量比2日介于1.2到2.5"],
  dropped: [{ kind: "entry", expression: "KDJ金叉", error: "无法识别条件" }]
};

function renderWorkbench(overrides: Partial<Parameters<typeof StrategyWorkbench>[0]> = {}) {
  const onStrategyChange = vi.fn();
  const props = {
    coverage: [],
    settings: defaultSettings,
    strategy: defaultStrategy,
    onSettingsChange: vi.fn(),
    onStrategyChange,
    conditionValidation: null,
    validationExamples: [],
    recommendedStrategies: [],
    savedStrategies: [],
    strategySaveMessage: null,
    onValidateCondition: vi.fn(),
    validateConditionText: vi.fn(),
    onApplySavedStrategy: vi.fn(),
    onDeleteSavedStrategy: vi.fn(),
    ...overrides
  };
  render(<StrategyWorkbench {...props} />);
  return { onStrategyChange };
}

it("keeps the manual condition editor collapsed until advanced mode is opened", () => {
  renderWorkbench();

  expect(screen.queryByLabelText("新增条件表达式")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "AI 理解并写入" })).toBeInTheDocument();
});

it("renders the AI parse checklist with approximation notes and writes selected conditions", async () => {
  const onParseConditions = vi.fn(async () => parseResult);
  const { onStrategyChange } = renderWorkbench({
    aiReady: true,
    onParseConditions
  });
  const user = userEvent.setup();

  await user.type(screen.getByLabelText("自然语言条件"), "近5天放量上涨，破20日线卖");
  await user.click(screen.getByRole("button", { name: "AI 理解并写入" }));

  await waitFor(() => expect(screen.getByLabelText("AI 解析的入场条件")).toBeInTheDocument());
  expect(screen.getByLabelText("AI 解析的离场条件")).toBeInTheDocument();
  expect(screen.getByText("『放量』→量比2日介于1.2到2.5")).toBeInTheDocument();
  expect(screen.getByText(/未识别：『KDJ金叉』/)).toBeInTheDocument();

  // 取消勾选第一条入场条件，确认写入策略时只写入勾选项。
  const parsePanel = screen.getByLabelText("AI 解析的入场条件").closest(".condition-parse-result") as HTMLElement;
  const checkboxes = within(parsePanel).getAllByRole("checkbox");
  expect(checkboxes).toHaveLength(3); // 2 entry + 1 exit
  await user.click(checkboxes[0]);

  await user.click(screen.getByRole("button", { name: "确认写入策略" }));

  expect(onStrategyChange).toHaveBeenCalledTimes(1);
  const written = onStrategyChange.mock.calls[0][0];
  expect(written.entry_groups[0].conditions).toHaveLength(3); // default 2 + 1 selected
  expect(written.exit_rules).toHaveLength(2); // default 1 + 1 selected
  expect(written.exit_rules[1].condition_id).toBe("close_below_ma");
});

it("disables the AI condition box when AI is not configured but keeps advanced mode usable", async () => {
  renderWorkbench({ aiReady: false, onParseConditions: vi.fn() });

  expect(screen.getByLabelText("自然语言条件")).toBeDisabled();
  expect(screen.getByRole("button", { name: "AI 理解并写入" })).toBeDisabled();

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /高级模式/ }));
  expect(screen.getByLabelText("新增条件表达式")).toBeEnabled();
});

it("runs the optimizer grid and renders the combination table with AI insight", async () => {
  const summary: OptimizeSummary = {
    combinations: [
      {
        index: 1,
        params: { fixed_holding_days: 3, take_profit_pct: 0.05 },
        metrics: {
          total_return_pct: 0.05,
          annualized_return_pct: 0.1,
          max_drawdown_pct: -0.03,
          win_rate_pct: 0.5,
          trade_count: 8,
          average_trade_return_pct: 0.004,
          average_position_pct: 0.35,
          max_position_pct: 0.5
        }
      },
      {
        index: 2,
        params: { fixed_holding_days: 5, take_profit_pct: 0.08 },
        metrics: {
          total_return_pct: 0.12,
          annualized_return_pct: 0.2,
          max_drawdown_pct: -0.02,
          win_rate_pct: 0.6,
          trade_count: 6,
          average_trade_return_pct: 0.006,
          average_position_pct: 0.35,
          max_position_pct: 0.5
        }
      }
    ],
    best: null,
    failures: [],
    total: 2,
    evaluated: 2,
    insight: "持有 5 天的组合整体占优，但组合数量少，注意过拟合。"
  };
  summary.best = summary.combinations[1];
  aiApi.runAiOptimizeStream.mockImplementation(
    async (_baseUrl: string, _request: unknown, handlers: { onCombination?: (c: unknown) => void; onProgress?: (p: unknown) => void; onResult?: (s: OptimizeSummary) => void }) => {
      for (const combination of summary.combinations) {
        handlers.onCombination?.(combination);
        handlers.onProgress?.({ completed: combination.index, total: 2 });
      }
      handlers.onResult?.(summary);
    }
  );

  render(<StrategyOptimizer strategy={defaultStrategy} settings={defaultSettings} baseUrl="http://127.0.0.1:9000" />);
  const user = userEvent.setup();

  expect(screen.getByRole("button", { name: "开始 AI 参数寻优" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "开始 AI 参数寻优" }));

  await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
  expect(screen.getByText("固定持仓天数 3 / 止盈比例（%） 5%")).toBeInTheDocument();
  expect(screen.getByText("固定持仓天数 5 / 止盈比例（%） 8%")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText(/注意过拟合/)).toBeInTheDocument());
  const bestRow = screen.getByText("固定持仓天数 5 / 止盈比例（%） 8%").closest("tr");
  expect(bestRow).toHaveClass("best-row");
});

it("renders the AI one-shot line and stays silent on failure", async () => {
  aiApi.aiInsightOneshot.mockResolvedValueOnce("本次回测交易次数偏少，建议扩大日期范围。");
  const { rerender } = render(
    <AiOneShotLine baseUrl="http://127.0.0.1:9000" scene="results_overview" context={{}} label="AI 回测短评" />
  );
  await waitFor(() => expect(screen.getByLabelText("AI 回测短评")).toHaveTextContent("本次回测交易次数偏少"));

  aiApi.aiInsightOneshot.mockRejectedValueOnce(new Error("ai_not_configured"));
  rerender(
    <AiOneShotLine key="retry" baseUrl="http://127.0.0.1:9000" scene="results_overview" context={{}} label="AI 回测短评" />
  );
  await waitFor(() => expect(aiApi.aiInsightOneshot).toHaveBeenCalledTimes(2));
  expect(screen.queryByLabelText("AI 回测短评")).not.toBeInTheDocument();
});

it("renders nothing without a base url", () => {
  render(<AiOneShotLine baseUrl={null} scene="risk_alerts" context={{}} label="AI 风险解读" />);
  expect(screen.queryByLabelText("AI 风险解读")).not.toBeInTheDocument();
});

it("builds a self-contained HTML report with metrics, svg curve and trades", () => {
  const result: BacktestResult = {
    metrics: {
      total_return_pct: 0.032,
      annualized_return_pct: 0.041,
      max_drawdown_pct: -0.018,
      win_rate_pct: 0.6,
      trade_count: 1,
      average_trade_return_pct: 0.011,
      average_position_pct: 0.48,
      max_position_pct: 0.48
    },
    equity_curve: [
      { trade_date: "2024-01-02", equity: 100000, cash: 100000, market_value: 0, drawdown_pct: 0 },
      { trade_date: "2024-01-08", equity: 103200, cash: 103200, market_value: 0, drawdown_pct: 0 }
    ],
    trades: [
      {
        symbol: "AAA",
        buy_signal_date: "2024-01-04",
        buy_date: "2024-01-05",
        sell_date: "2024-01-08",
        buy_price: 12,
        sell_price: 10.2,
        shares: 4000,
        planned_amount: 50000,
        buy_amount: 48000,
        sell_amount: 40800,
        target_position_pct: 0.5,
        actual_position_pct: 0.48,
        buy_reason: ["收盘价站上20日均线"],
        sell_reason: ["fixed holding days reached"],
        blocked_reason: null,
        pnl: -7200,
        pnl_pct: -0.15
      }
    ],
    preflight_issues: []
  };

  const html = buildBacktestReportHtml({
    result,
    strategy: defaultStrategy,
    settings: defaultSettings,
    aiCommentary: "交易次数偏少，注意样本量。"
  });

  expect(html).toContain("<!DOCTYPE html>");
  expect(html).toContain("总收益");
  expect(html).toContain("3.20%");
  expect(html).toContain("<svg");
  expect(html).toContain("AAA");
  expect(html).toContain("AI 解读");
  expect(html).toContain("不构成投资建议");
  expect(html).not.toContain("<script");
});
