import type { ComponentProps } from "react";
import { render, screen, within } from "@testing-library/react";
import { RecommendedStrategies } from "./RecommendedStrategies";

type RecommendedStrategiesProps = ComponentProps<typeof RecommendedStrategies>;

const items = [
  {
    id: "volume-breakout",
    name: "放量突破",
    description: "价格突破前高并伴随量能放大，适合寻找强势启动点。",
    suitable_market: "指数温和上行、红盘家数占优时使用。",
    risk_note: "避免连续大涨后追高，最好配合止损和市值过滤。",
    example_conditions: ["突破20日新高", "量比2日介于1.2到2.5", "近5日涨幅小于12%"],
    scenario: "温和上行",
    featured: true,
    required_datasets: ["daily_bars", "market_cap"],
    capability_note: "当前本地数据完整，可直接运行。",
    strategy: {
      name: "放量突破",
      market_filters: [],
      entry_groups: [{ id: "entry", operator: "and", conditions: [] }],
      exit_rules: []
    }
  },
  {
    id: "market-balance",
    name: "市值量价均衡",
    description: "过滤超大市值和极端成交，寻找流动性适中的趋势机会。",
    suitable_market: "震荡偏强或结构性行情中使用。",
    risk_note: "资金面缺失时应降低信号置信度。",
    example_conditions: ["流通市值10亿到300亿", "换手率2%到8%"],
    scenario: "震荡偏强",
    featured: true,
    required_datasets: ["daily_bars", "market_cap"],
    capability_note: "适合本地已有市值覆盖的回测区间。",
    strategy: {
      name: "市值量价均衡",
      market_filters: [],
      entry_groups: [{ id: "entry", operator: "and", conditions: [] }],
      exit_rules: []
    }
  },
  {
    id: "capital-trend",
    name: "资金趋势跟随",
    description: "把主力净流入与均线趋势结合，优先选择资金确认的趋势股。",
    suitable_market: "主线明确、成交活跃时使用。",
    risk_note: "需要本地资金流数据完整，否则只适合作参考。",
    example_conditions: ["近3日主力净流入大于300万", "收盘价站上20日均线"],
    scenario: "主线共振",
    featured: true,
    required_datasets: ["daily_bars", "capital_flow"],
    capability_note: "资金流覆盖完整时效果更稳定。",
    strategy: {
      name: "资金趋势跟随",
      market_filters: [],
      entry_groups: [{ id: "entry", operator: "and", conditions: [] }],
      exit_rules: []
    }
  },
  {
    id: "low-absorption",
    name: "缩量回踩承接",
    description: "回踩均线不破并观察承接，适合温和行情中的低吸确认。",
    suitable_market: "热点轮动但指数不弱时使用。",
    risk_note: "跌破支撑位后要快速止损。",
    example_conditions: ["收盘价站上10日均线", "量比2日介于0.8到1.5"],
    scenario: "温和上行",
    featured: false,
    required_datasets: ["daily_bars"],
    capability_note: "只依赖日线数据，可作为基础方案。",
    strategy: {
      name: "缩量回踩承接",
      market_filters: [],
      entry_groups: [{ id: "entry", operator: "and", conditions: [] }],
      exit_rules: []
    }
  }
] as unknown as RecommendedStrategiesProps["items"];

it("renders a featured section and a scenario-grouped section", () => {
  render(<RecommendedStrategies items={items} onApply={() => {}} />);

  const featuredSection = screen.getByRole("region", { name: "精选主推" });
  const scenarioSection = screen.getByRole("region", { name: "按行情场景选择" });

  expect(within(featuredSection).getByRole("heading", { name: "当前可直接运行的策略" })).toBeInTheDocument();
  expect(within(featuredSection).getAllByRole("button", { name: /套用/ })).toHaveLength(3);
  expect(within(featuredSection).getByText("当前本地数据完整，可直接运行。")).toBeInTheDocument();

  expect(within(scenarioSection).getByRole("heading", { name: "根据盘面状态找备选策略" })).toBeInTheDocument();
  expect(within(scenarioSection).getByRole("heading", { name: "温和上行" })).toBeInTheDocument();
  expect(within(scenarioSection).getByRole("heading", { name: "震荡偏强" })).toBeInTheDocument();
  expect(within(scenarioSection).getByRole("heading", { name: "主线共振" })).toBeInTheDocument();
  expect(within(scenarioSection).getByText("缩量回踩承接")).toBeInTheDocument();
});
