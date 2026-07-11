import { lazy, Suspense, useEffect, useState } from "react";
import { Activity, Database, Flame, Gauge, ShieldAlert } from "lucide-react";
import {
  loadClsFinance,
  loadMarketBriefing,
  loadMarketNews,
  loadNewsSummary,
  loadRealtimeMarketSnapshot,
  loadRealtimeMarketSnapshotStream,
  loadRecommendedStrategies,
  loadRiskAlerts,
  runBacktestStreamWithDataService,
  runConfiguredBacktest,
  validateConditionExpression,
  validateStockSymbols
} from "./api";
import { ClsFinancePanel } from "./components/ClsFinancePanel";
import { DataCenter } from "./components/DataCenter";
import { MarketDashboard } from "./components/MarketDashboard";
import { NewsPanel } from "./components/NewsPanel";
import { NewsSummaryPanel } from "./components/NewsSummaryPanel";
import { RiskAlertsModal } from "./components/RiskAlertsModal";
import {
  cloneStrategyConfig,
  createSavedStrategyPreset,
  hasSavableRules,
  strategySignature
} from "./savedStrategies";
import { useSavedStrategyStore } from "./useSavedStrategyStore";
import { StrategyWorkbench } from "./components/StrategyWorkbench";
import { TradesTable } from "./components/TradesTable";
import { TonghuashunBriefingPanel } from "./components/TonghuashunBriefingPanel";
import { UpdatePanel } from "./components/UpdatePanel";
import { detectMarketSessionPhase, initialMarketRefreshMeta, refreshIntervalForPhase } from "./marketRefresh";
import { defaultSettings, defaultStrategy } from "./strategyDefaults";
import type {
  BacktestResult,
  BacktestSettingsConfig,
  DataServiceStatus,
  DatasetCoverage,
  ConditionValidationResult,
  ClsFinanceResponse,
  MarketBriefingResponse,
  MarketRefreshMeta,
  MarketNewsResponse,
  NewsSummaryResponse,
  RealtimeMarketSnapshot,
  RecommendedStrategy,
  RiskAlertsResponse,
  SavedStrategyPreset,
  StockSymbolValidationResult,
  StrategyConfig
} from "./types";

type PendingStrategySave = {
  strategy: StrategyConfig;
  name: string;
} | null;

const ResultsOverview = lazy(() => import("./components/ResultsOverview").then((module) => ({
  default: module.ResultsOverview
})));

const A_SHARE_HOLIDAY_RANGES: Record<number, Array<[string, string]>> = {
  2024: [
    ["2024-01-01", "2024-01-01"],
    ["2024-02-09", "2024-02-17"],
    ["2024-04-04", "2024-04-06"],
    ["2024-05-01", "2024-05-05"],
    ["2024-06-10", "2024-06-10"],
    ["2024-09-15", "2024-09-17"],
    ["2024-10-01", "2024-10-07"]
  ],
  2025: [
    ["2025-01-01", "2025-01-01"],
    ["2025-01-28", "2025-02-04"],
    ["2025-04-04", "2025-04-06"],
    ["2025-05-01", "2025-05-05"],
    ["2025-05-31", "2025-06-02"],
    ["2025-10-01", "2025-10-08"]
  ],
  2026: [
    ["2026-01-01", "2026-01-03"],
    ["2026-02-15", "2026-02-23"],
    ["2026-04-04", "2026-04-06"],
    ["2026-05-01", "2026-05-05"],
    ["2026-06-19", "2026-06-21"],
    ["2026-09-25", "2026-09-27"],
    ["2026-10-01", "2026-10-07"]
  ]
};

function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isAShareTradingDay(date: Date): boolean {
  if (date.getDay() === 0 || date.getDay() === 6) {
    return false;
  }
  const text = formatLocalDate(date);
  return !(A_SHARE_HOLIDAY_RANGES[date.getFullYear()] ?? []).some(
    ([start, end]) => start <= text && text <= end
  );
}

function recentTradingDateRangeEnding(endDate: string, days = 5): { startDate: string; endDate: string } {
  const end = new Date(`${endDate}T00:00:00`);
  const start = new Date(end);
  let counted = 1;
  while (counted < days) {
    start.setDate(start.getDate() - 1);
    if (isAShareTradingDay(start)) {
      counted += 1;
    }
  }
  return { startDate: formatLocalDate(start), endDate };
}

function latestDailyCoverage(coverage: DatasetCoverage[]): DatasetCoverage | undefined {
  return coverage.find((item) => item.dataset === "daily_bars");
}

function formatPercent(value: number | null | undefined): string {
  return value == null ? "--" : `${(value * 100).toFixed(2)}%`;
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatMarketDegree(value: number | null | undefined): string {
  return value == null ? "--" : value.toFixed(1);
}

function marketDegreeCardClass(value: number | null | undefined): string {
  if (value == null) {
    return "";
  }
  if (value >= 5) {
    return "market-degree-card-high";
  }
  if (value < 4) {
    return "market-degree-card-low";
  }
  return "market-degree-card-neutral";
}

function marketDegreeTextClass(value: number | null | undefined): "up-text" | "down-text" | "flat-text" | undefined {
  if (value == null) {
    return undefined;
  }
  if (value >= 5) {
    return "up-text";
  }
  if (value < 4) {
    return "down-text";
  }
  return "flat-text";
}

function translateError(message: string): string {
  if (message.includes("No cached daily bars found")) {
    return "未找到已缓存的日线行情，请先确认 a-stock-data 数据包已导入到本地缓存。";
  }
  if (message.includes("Selected strategy requires capital-flow data")) {
    return "当前策略需要资金流向数据，请检查数据中心的资金流向覆盖情况。";
  }
  if (message.includes("Required column is missing")) {
    return "历史数据字段不完整，请在数据中心补齐所选策略需要的行情、资金或市值字段。";
  }
  if (message.includes("unknown condition_id")) {
    return "策略条件暂不支持，请从条件库中选择已注册的 A 股条件。";
  }
  if (
    message.includes("must be") ||
    message.includes("condition group") ||
    message.includes("strategy must") ||
    message.includes("end_date")
  ) {
    return "回测参数不合法，请检查日期、资金、持仓、费用和止盈止损设置。";
  }
  return "回测运行失败，请检查数据中心覆盖范围和策略参数。";
}

function validateBacktestSettings(settings: BacktestSettingsConfig, draftErrors: string[]): string[] {
  const errors = [...draftErrors];
  if (!settings.start_date) {
    errors.push("开始日期不能为空。");
  }
  if (!settings.end_date) {
    errors.push("结束日期不能为空。");
  }
  if (settings.start_date && settings.end_date && settings.start_date > settings.end_date) {
    errors.push("开始日期不能晚于结束日期。");
  }
  if (!Number.isFinite(settings.initial_cash) || settings.initial_cash <= 0) {
    errors.push("初始资金必须大于0。");
  }
  if (!Number.isFinite(settings.position_size_pct) || settings.position_size_pct <= 0 || settings.position_size_pct > 1) {
    errors.push("个股仓位上限必须大于0且不能超过100%。");
  }
  if (!Number.isInteger(settings.fixed_holding_days) || settings.fixed_holding_days < 1) {
    errors.push("固定持仓天数必须至少为1天。");
  }
  if (!Number.isInteger(settings.max_positions) || settings.max_positions < 1) {
    errors.push("最大持仓数必须至少为1。");
  }
  if (!Number.isInteger(settings.max_daily_buys) || settings.max_daily_buys < 1) {
    errors.push("每日最多买入必须至少为1。");
  }
  if (settings.take_profit_pct != null && (!Number.isFinite(settings.take_profit_pct) || settings.take_profit_pct <= 0)) {
    errors.push("止盈比例必须为正数。");
  }
  if (settings.stop_loss_pct != null && (!Number.isFinite(settings.stop_loss_pct) || settings.stop_loss_pct >= 0)) {
    errors.push("止损比例必须为负数。");
  }
  if (!Number.isFinite(settings.slippage_rate) || settings.slippage_rate < 0) {
    errors.push("滑点比例不能小于0。");
  }
  if (!Number.isFinite(settings.fee_rate) || settings.fee_rate < 0) {
    errors.push("手续费率不能小于0。");
  }
  if (!Number.isFinite(settings.stamp_tax_rate) || settings.stamp_tax_rate < 0) {
    errors.push("印花税率不能小于0。");
  }
  if (!Number.isInteger(settings.min_listing_days) || settings.min_listing_days < 0) {
    errors.push("最少上市天数不能小于0。");
  }
  if (settings.stock_pool === "custom" && settings.custom_symbols.length === 0) {
    errors.push("股票池为自选代码时，至少需要填写一个股票代码。");
  }
  return [...new Set(errors)];
}

type BacktestTrade = BacktestResult["trades"][number];

function tradeIdentity(trade: BacktestTrade): string {
  return `${trade.symbol}-${trade.buy_signal_date}-${trade.buy_date}`;
}

function mergeBacktestTrades(current: BacktestTrade[], incoming: BacktestTrade[]): BacktestTrade[] {
  const incomingKeys = new Set(incoming.map(tradeIdentity));
  return [
    ...incoming,
    ...current.filter((trade) => !incomingKeys.has(tradeIdentity(trade)))
  ];
}

export function App() {
  const [coverage, setCoverage] = useState<DatasetCoverage[]>([]);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [streamedTrades, setStreamedTrades] = useState<BacktestResult["trades"]>([]);
  const [strategy, setStrategy] = useState<StrategyConfig>(defaultStrategy);
  const [settings, setSettings] = useState<BacktestSettingsConfig>(defaultSettings);
  const [error, setError] = useState<string | null>(null);
  const [dataService, setDataService] = useState<DataServiceStatus | null>(null);
  const [isRunningBacktest, setIsRunningBacktest] = useState(false);
  const [runPhases, setRunPhases] = useState<string[]>([]);
  const [runProgressMessage, setRunProgressMessage] = useState<string | null>(null);
  const [marketSnapshot, setMarketSnapshot] = useState<RealtimeMarketSnapshot | null>(null);
  const [marketRefreshMeta, setMarketRefreshMeta] = useState<MarketRefreshMeta>(() => initialMarketRefreshMeta());
  const [isLoadingMarket, setIsLoadingMarket] = useState(false);
  const [marketNews, setMarketNews] = useState<MarketNewsResponse | null>(null);
  const [clsFinance, setClsFinance] = useState<ClsFinanceResponse | null>(null);
  const [newsSummary, setNewsSummary] = useState<NewsSummaryResponse | null>(null);
  const [fupanBriefing, setFupanBriefing] = useState<MarketBriefingResponse | null>(null);
  const [zaopanBriefing, setZaopanBriefing] = useState<MarketBriefingResponse | null>(null);
  const [isLoadingNews, setIsLoadingNews] = useState(false);
  const [riskAlerts, setRiskAlerts] = useState<RiskAlertsResponse | null>(null);
  const [isLoadingRiskAlerts, setIsLoadingRiskAlerts] = useState(false);
  const [riskModalOpen, setRiskModalOpen] = useState(false);
  const [recommendedStrategies, setRecommendedStrategies] = useState<RecommendedStrategy[]>([]);
  // Persistence lifecycle (loading/ready/failed), single initial load, serialized
  // mutations and out-of-order-load protection are all owned by the store.
  const {
    store: savedStrategyStore,
    strategies: savedStrategies,
    status: strategyLoadStatus,
    isMutating: isMutatingStrategies,
    error: strategyLoadError
  } = useSavedStrategyStore();
  const [conditionValidation, setConditionValidation] = useState<ConditionValidationResult | null>(null);
  const [isValidatingCondition, setIsValidatingCondition] = useState(false);
  const [stockSymbolValidation, setStockSymbolValidation] = useState<StockSymbolValidationResult | null>(null);
  const [isValidatingStockSymbols, setIsValidatingStockSymbols] = useState(false);
  const [settingsDraftErrors, setSettingsDraftErrors] = useState<string[]>([]);
  const [strategySaveMessage, setStrategySaveMessage] = useState<string | null>(null);
  const [pendingStrategySave, setPendingStrategySave] = useState<PendingStrategySave>(null);
  const [settingsDateTouched, setSettingsDateTouched] = useState(false);

  useEffect(() => {
    if (strategyLoadStatus === "failed" && strategyLoadError) {
      setStrategySaveMessage(`加载已保存策略失败，仅显示内置策略：${strategyLoadError}`);
    }
  }, [strategyLoadStatus, strategyLoadError]);

  const queueStrategySavePrompt = (currentStrategy: StrategyConfig) => {
    const hasCustomEntryRule = currentStrategy.entry_groups.some((group) =>
      group.conditions.some((condition) => Boolean(condition.expression?.trim()))
    );
    const hasCustomExitRule = currentStrategy.exit_rules.some((condition) => Boolean(condition.expression?.trim()));
    if (
      !hasSavableRules(currentStrategy) ||
      !hasCustomEntryRule ||
      !hasCustomExitRule ||
      strategySignature(currentStrategy) === strategySignature(defaultStrategy)
    ) {
      setPendingStrategySave(null);
      return;
    }
    const existing = savedStrategies.find((item) => strategySignature(item.strategy) === strategySignature(currentStrategy));
    if (existing) {
      setPendingStrategySave(null);
      setStrategySaveMessage(`当前策略已保存在“${existing.name}”中。`);
      return;
    }
    const nextPreset = createSavedStrategyPreset(currentStrategy, savedStrategies);
    setPendingStrategySave({
      strategy: cloneStrategyConfig(currentStrategy),
      name: nextPreset.name
    });
    setStrategySaveMessage("回测完成，可将当前入场与离场规则保存到策略配置。");
  };

  const confirmPendingStrategySave = async () => {
    if (!pendingStrategySave || isMutatingStrategies) {
      return;
    }
    // The store waits for the single initial load, refuses to persist unless the
    // load succeeded, and serializes this against any other save/delete.
    const result = await savedStrategyStore.save(pendingStrategySave.strategy);
    if (result.ok) {
      setStrategySaveMessage(`已保存策略：${result.savedName ?? pendingStrategySave.name}`);
      setPendingStrategySave(null);
    } else {
      setStrategySaveMessage(result.error ? `策略保存失败：${result.error}` : "策略保存失败。");
    }
  };

  const dismissPendingStrategySave = () => {
    setPendingStrategySave(null);
    setStrategySaveMessage("本次未保存策略，你可以继续调整后再次运行。");
  };

  const handleCoverageChange = (nextCoverage: DatasetCoverage[]) => {
    setCoverage(nextCoverage);
  };

  const handleSettingsChange = (nextSettings: BacktestSettingsConfig) => {
    setSettings((current) => {
      if (nextSettings.start_date !== current.start_date || nextSettings.end_date !== current.end_date) {
        setSettingsDateTouched(true);
      }
      if (
        nextSettings.stock_pool !== current.stock_pool ||
        nextSettings.custom_symbols.join(",") !== current.custom_symbols.join(",")
      ) {
        setStockSymbolValidation(null);
      }
      return nextSettings;
    });
  };

  useEffect(() => {
    if (settingsDateTouched) {
      return;
    }
    const daily = latestDailyCoverage(coverage);
    if (!daily?.end_date) {
      return;
    }
    const today = formatLocalDate(new Date());
    const effectiveEndDate = daily.end_date < today ? daily.end_date : today;
    const range = recentTradingDateRangeEnding(effectiveEndDate);
    setSettings((current) => {
      if (current.start_date === range.startDate && current.end_date === range.endDate) {
        return current;
      }
      return {
        ...current,
        start_date: range.startDate,
        end_date: range.endDate
      };
    });
  }, [coverage, settingsDateTouched]);

  const runBacktest = async () => {
    const validationErrors = validateBacktestSettings(settings, settingsDraftErrors);
    if (validationErrors.length > 0) {
      setError(validationErrors.join(" "));
      setRunProgressMessage(null);
      setRunPhases([]);
      return;
    }
    if (settings.stock_pool === "custom") {
      const symbolValidation = await validateCustomStockSymbols(settings.custom_symbols);
      if (!symbolValidation?.ok) {
        const invalidSymbols = symbolValidation?.invalid_symbols.length
          ? symbolValidation.invalid_symbols.join("、")
          : settings.custom_symbols.join("、");
        setError(`自选代码包含无效股票代码：${invalidSymbols}`);
        setRunProgressMessage(null);
        setRunPhases([]);
        return;
      }
    }
    try {
      setError(null);
      setResult(null);
      setStreamedTrades([]);
      setIsRunningBacktest(true);
      setRunProgressMessage("正在准备历史数据与策略条件。");
      setRunPhases(["校验参数", "读取本地数据"]);
      window.setTimeout(() => setRunPhases((current) => (current.length < 3 ? [...current, "计算指标"] : current)), 120);
      window.setTimeout(() => setRunPhases((current) => (current.length < 4 ? [...current, "撮合交易"] : current)), 260);
      const nextResult = dataService
        ? await runBacktestStreamWithDataService(dataService.base_url, strategy, settings, {
            onPhase: (phase) =>
              setRunPhases((current) => (current.includes(phase) ? current : [...current, phase])),
            onProgress: (event) => setRunProgressMessage(event.message),
            onTrade: (trade) =>
              setStreamedTrades((current) => mergeBacktestTrades(current, [trade])),
            onResult: (completed) => {
              setResult(completed);
              setStreamedTrades((current) => mergeBacktestTrades(current, completed.trades));
              setRunProgressMessage("回测完成，已生成收益曲线和交易明细。");
            }
          })
        : await runConfiguredBacktest(strategy, settings);
      setResult(nextResult);
      setStreamedTrades((current) => mergeBacktestTrades(current, nextResult.trades));
      queueStrategySavePrompt(strategy);
      setRunPhases(["校验参数", "读取本地数据", "计算指标", "撮合交易", "生成结果"]);
    } catch (caught) {
      setError(caught instanceof Error ? translateError(caught.message) : "回测运行失败。");
      setRunProgressMessage(null);
    } finally {
      setIsRunningBacktest(false);
    }
  };

  useEffect(() => {
    if (!dataService) {
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    let activeRequest: AbortController | undefined;
    const refreshMarket = async () => {
      const requestController = new AbortController();
      activeRequest = requestController;
      const phase = detectMarketSessionPhase();
      let nextRefreshMs = refreshIntervalForPhase(phase);
      setIsLoadingMarket(true);
      setMarketRefreshMeta((current) => ({
        ...current,
        phase,
        status: "refreshing",
        message: current.last_success_at ? "刷新中，保留上一份成功快照" : "刷新中",
        next_refresh_ms: refreshIntervalForPhase(phase)
      }));
      try {
        const applySnapshot = (snapshot: RealtimeMarketSnapshot, isPartial = false) => {
          if (cancelled) {
            return;
          }
          setMarketSnapshot((current) => (snapshot.status === "unavailable" && current ? current : snapshot));
          const nextPhase = snapshot.market_phase ?? phase;
          setMarketRefreshMeta((current) => {
            const usingLastSuccess = snapshot.status === "unavailable" && Boolean(current.last_success_at);
            nextRefreshMs = refreshIntervalForPhase(nextPhase, snapshot.status === "unavailable");
            return {
              phase: nextPhase,
              status: isPartial ? "refreshing" : usingLastSuccess ? "using_last_success" : snapshot.status === "unavailable" ? "unavailable" : "idle",
              message:
                isPartial
                  ? snapshot.message
                  : usingLastSuccess
                  ? "实时接口暂不可用，使用最近数据"
                  : snapshot.status === "unavailable"
                    ? "实时接口暂不可用"
                    : nextPhase === "trading"
                      ? "实时行情已更新"
                      : "非交易时段，使用最近数据",
              last_success_at: isPartial
                ? current.last_success_at ?? null
                : snapshot.status === "unavailable"
                  ? current.last_success_at ?? null
                  : snapshot.updated_at,
              last_error: snapshot.status === "unavailable" ? snapshot.message : undefined,
              next_refresh_ms: nextRefreshMs
            };
          });
        };
        const snapshot = await loadRealtimeMarketSnapshotStream(dataService.base_url, {
          onSnapshot: (partial) => applySnapshot(partial, true)
        }, { signal: requestController.signal });
        applySnapshot(snapshot);
      } catch (caught) {
        if (cancelled || requestController.signal.aborted) {
          return;
        }
        try {
          const snapshot = await loadRealtimeMarketSnapshot(dataService.base_url);
          if (!cancelled) {
            setMarketSnapshot((current) => (snapshot.status === "unavailable" && current ? current : snapshot));
            const nextPhase = snapshot.market_phase ?? phase;
            setMarketRefreshMeta((current) => {
              const usingLastSuccess = snapshot.status === "unavailable" && Boolean(current.last_success_at);
              nextRefreshMs = refreshIntervalForPhase(nextPhase, snapshot.status === "unavailable");
              return {
                phase: nextPhase,
                status: usingLastSuccess ? "using_last_success" : snapshot.status === "unavailable" ? "unavailable" : "idle",
                message:
                  usingLastSuccess
                    ? "实时接口暂不可用，使用最近数据"
                    : snapshot.status === "unavailable"
                      ? "实时接口暂不可用"
                      : nextPhase === "trading"
                        ? "实时行情已更新"
                        : "非交易时段，使用最近数据",
                last_success_at: snapshot.status === "unavailable" ? current.last_success_at ?? null : snapshot.updated_at,
                last_error: snapshot.status === "unavailable" ? snapshot.message : undefined,
                next_refresh_ms: nextRefreshMs
              };
            });
          }
        } catch (fallbackCaught) {
          if (!cancelled) {
            const reason = fallbackCaught instanceof Error
              ? fallbackCaught.message
              : caught instanceof Error
                ? caught.message
                : "请求失败";
            setMarketRefreshMeta((current) => ({
              phase,
              status: current.last_success_at ? "using_last_success" : "unavailable",
              message: current.last_success_at ? "实时接口暂不可用，使用最近数据" : "实时接口暂不可用",
              last_success_at: current.last_success_at ?? null,
              last_error: reason,
              next_refresh_ms: refreshIntervalForPhase(phase, true)
            }));
            nextRefreshMs = refreshIntervalForPhase(phase, true);
          }
        }
      } finally {
        if (activeRequest === requestController) {
          activeRequest = undefined;
        }
        if (!cancelled) {
          setIsLoadingMarket(false);
          timer = window.setTimeout(refreshMarket, nextRefreshMs);
        }
      }
    };
    void refreshMarket();
    return () => {
      cancelled = true;
      activeRequest?.abort();
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [dataService]);

  const refreshNews = async () => {
    if (!dataService) {
      return;
    }
    setIsLoadingNews(true);
    try {
      const [newsResult, fupanResult, zaopanResult, financeResult, summaryResult] = await Promise.allSettled([
        loadMarketNews(dataService.base_url),
        loadMarketBriefing(dataService.base_url, "fupan"),
        loadMarketBriefing(dataService.base_url, "zaopan"),
        loadClsFinance(dataService.base_url),
        loadNewsSummary(dataService.base_url)
      ]);
      if (newsResult.status === "fulfilled") {
        setMarketNews(newsResult.value);
      }
      if (fupanResult.status === "fulfilled") {
        setFupanBriefing(fupanResult.value);
      }
      if (zaopanResult.status === "fulfilled") {
        setZaopanBriefing(zaopanResult.value);
      }
      if (financeResult.status === "fulfilled") {
        setClsFinance(financeResult.value);
      }
      if (summaryResult.status === "fulfilled") {
        setNewsSummary(summaryResult.value);
      }
    } finally {
      setIsLoadingNews(false);
    }
  };

  const refreshRiskAlerts = async () => {
    if (!dataService) {
      return;
    }
    setIsLoadingRiskAlerts(true);
    try {
      setRiskAlerts(await loadRiskAlerts(dataService.base_url));
    } finally {
      setIsLoadingRiskAlerts(false);
    }
  };

  const validateConditionText = async (text: string, mode: "entry" | "exit" = "entry"): Promise<ConditionValidationResult> => {
    if (!dataService) {
      return {
        ok: false,
        normalized_text: text.trim(),
        condition: null,
        errors: [{ code: "service_unavailable", message: "本地数据服务未连接，暂时无法校验条件。" }],
        examples: mode === "exit" ? ["收盘价跌破3日均线", "跌破20日低点"] : ["收盘价站上20日均线", "量比2日介于1.2到2.5"]
      };
    }
    return validateConditionExpression(dataService.base_url, text, mode);
  };

  const validateCustomStockSymbols = async (symbols: string[]): Promise<StockSymbolValidationResult | null> => {
    const requested = symbols.map((symbol) => symbol.trim()).filter(Boolean);
    if (requested.length === 0) {
      const emptyResult: StockSymbolValidationResult = {
        ok: false,
        valid_symbols: [],
        invalid_symbols: [],
        normalized_symbols: [],
        source: "empty"
      };
      setStockSymbolValidation(emptyResult);
      return emptyResult;
    }
    if (!dataService) {
      const serviceUnavailable: StockSymbolValidationResult = {
        ok: false,
        valid_symbols: [],
        invalid_symbols: requested,
        normalized_symbols: requested,
        source: "service-unavailable"
      };
      setStockSymbolValidation(serviceUnavailable);
      return serviceUnavailable;
    }
    setIsValidatingStockSymbols(true);
    try {
      const result = await validateStockSymbols(dataService.base_url, requested);
      setStockSymbolValidation(result);
      return result;
    } catch {
      const failed: StockSymbolValidationResult = {
        ok: false,
        valid_symbols: [],
        invalid_symbols: requested,
        normalized_symbols: requested,
        source: "request-failed"
      };
      setStockSymbolValidation(failed);
      return failed;
    } finally {
      setIsValidatingStockSymbols(false);
    }
  };

  const handleValidateCondition = async (text: string) => {
    setIsValidatingCondition(true);
    try {
      setConditionValidation(await validateConditionText(text));
    } catch (caught) {
      setConditionValidation({
        ok: false,
        normalized_text: text.trim(),
        condition: null,
        errors: [{ code: "request_failed", message: caught instanceof Error ? caught.message : "条件校验失败。" }],
        examples: ["收盘价站上20日均线", "量比2日介于1.2到2.5"]
      });
    } finally {
      setIsValidatingCondition(false);
    }
  };

  useEffect(() => {
    if (!dataService) {
      return;
    }
    let cancelled = false;
    const loadAuxiliaryData = async () => {
      const [newsResult, fupanResult, zaopanResult, financeResult, summaryResult, riskResult, recommendedResult] = await Promise.allSettled([
        loadMarketNews(dataService.base_url),
        loadMarketBriefing(dataService.base_url, "fupan"),
        loadMarketBriefing(dataService.base_url, "zaopan"),
        loadClsFinance(dataService.base_url),
        loadNewsSummary(dataService.base_url),
        loadRiskAlerts(dataService.base_url),
        loadRecommendedStrategies(dataService.base_url)
      ]);
      if (cancelled) {
        return;
      }
      if (newsResult.status === "fulfilled") {
        setMarketNews(newsResult.value);
      }
      if (fupanResult.status === "fulfilled") {
        setFupanBriefing(fupanResult.value);
      }
      if (zaopanResult.status === "fulfilled") {
        setZaopanBriefing(zaopanResult.value);
      }
      if (financeResult.status === "fulfilled") {
        setClsFinance(financeResult.value);
      }
      if (summaryResult.status === "fulfilled") {
        setNewsSummary(summaryResult.value);
      }
      if (riskResult.status === "fulfilled") {
        setRiskAlerts(riskResult.value);
      }
      if (recommendedResult.status === "fulfilled") {
        setRecommendedStrategies(recommendedResult.value.items);
      }
    };
    void loadAuxiliaryData();
    const timer = window.setInterval(() => {
      void refreshNews();
      void refreshRiskAlerts();
    }, 120_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [dataService]);

  const coverageSymbols = coverage.reduce((sum, item) => sum + item.symbols, 0);
  const liveHeatRatio = marketSnapshot?.breadth && marketSnapshot.breadth.total > 0
    ? marketSnapshot.breadth.up / marketSnapshot.breadth.total
    : null;
  const marketDegreeSource = clsFinance?.emotion?.market_degree_source;
  const hasTonghuashunMarketDegree = marketDegreeSource === "ths-market-summary";
  const marketDegree = hasTonghuashunMarketDegree ? clsFinance?.emotion?.market_degree : null;
  const marketDegreeLabel = hasTonghuashunMarketDegree
    ? clsFinance?.emotion?.market_degree_label ?? "同花顺大盘评级"
    : "同花顺大盘评级";
  const marketDegreeNote = marketDegree == null
    ? isLoadingNews ? "正在读取同花顺大盘评分" : "同花顺评分暂不可用"
    : marketDegreeLabel;
  const issueCount = result?.preflight_issues.length ?? 0;
  const riskAlertCount = riskAlerts?.items.length ?? 0;
  const closedTrades = result?.metrics.trade_count ?? 0;
  const visibleTrades = result ? mergeBacktestTrades(streamedTrades, result.trades) : streamedTrades;
  const poolLabel = {
    all: "全A",
    main_board: "沪深主板",
    gem: "创业板",
    star: "科创板",
    beijing: "北交所",
    custom: settings.custom_symbols.length > 0 ? `自选 ${settings.custom_symbols.length} 只` : "自选代码"
  }[settings.stock_pool];
  const marketBreadthLabel = marketSnapshot?.breadth
    ? marketSnapshot.status === "live"
      ? `今日实时红盘 ${marketSnapshot.breadth.up} / 全市场 ${marketSnapshot.breadth.total}`
      : `本地最近交易日/非实时 红盘 ${marketSnapshot.breadth.up} / 样本 ${marketSnapshot.breadth.total}`
    : `${poolLabel} / 等待实时行情`;

  const applySavedStrategy = (preset: SavedStrategyPreset) => {
    setStrategy(cloneStrategyConfig(preset.strategy));
    setStrategySaveMessage(`已套用已保存策略：${preset.name}`);
  };

  const deleteSavedStrategy = async (presetId: string) => {
    if (isMutatingStrategies) {
      return;
    }
    // The store waits for the single initial load, refuses to persist unless the
    // load succeeded, and serializes this against any other save/delete.
    const result = await savedStrategyStore.remove(presetId);
    if (result.ok) {
      setStrategySaveMessage(result.removedName ? `已删除已保存策略：${result.removedName}` : "已删除已保存策略。");
    } else {
      setStrategySaveMessage(result.error ?? "删除策略失败。");
    }
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="topbar-copy">
          <span className="eyebrow">A股历史回测</span>
          <h1>A股策略回测工作台</h1>
          <p>基于本地 a-stock-data 历史数据，调参、回滚、查看策略预期收益。</p>
        </div>
        <div className="topbar-actions" aria-label="运行状态">
          <UpdatePanel />
          <span className="status-pill"><Activity size={16} aria-hidden="true" /> 保守日线撮合</span>
          <span className="status-pill"><Database size={16} aria-hidden="true" /> 本地缓存</span>
        </div>
      </header>
      <div className="market-news-layout">
        <MarketDashboard snapshot={marketSnapshot} isLoading={isLoadingMarket} refreshMeta={marketRefreshMeta} />
        <NewsPanel news={marketNews} isLoading={isLoadingNews} onRefresh={refreshNews} />
      </div>
      <div className="market-insight-layout">
        <ClsFinancePanel finance={clsFinance} isLoading={isLoadingNews} />
        <NewsSummaryPanel summary={newsSummary} isLoading={isLoadingNews} />
      </div>
      <TonghuashunBriefingPanel fupan={fupanBriefing} zaopan={zaopanBriefing} />
      <section className="summary-band" aria-label="工作台概览">
        <article className="summary-card heat-card">
          <div>
            <span>市场热度</span>
            <strong>{formatPercent(liveHeatRatio)}</strong>
          </div>
          <Flame size={24} aria-hidden="true" />
          <small>{marketBreadthLabel}</small>
        </article>
        <article className={`summary-card market-degree-card ${marketDegreeCardClass(marketDegree)}`.trim()}>
          <div>
            <span>大盘评分</span>
            <strong className={marketDegreeTextClass(marketDegree)}>{formatMarketDegree(marketDegree)}</strong>
          </div>
          <Gauge size={24} aria-hidden="true" />
          <small>{marketDegreeNote}</small>
        </article>
        <article className="summary-card">
          <div>
            <span>收益表现</span>
            <strong>{formatPercent(result?.metrics.total_return_pct)}</strong>
          </div>
          <Activity size={24} aria-hidden="true" />
          <small>最大回撤 {formatPercent(result?.metrics.max_drawdown_pct)} / {closedTrades} 笔交易</small>
        </article>
        <button
          className="summary-card summary-card-button"
          type="button"
          aria-label={`查看全市场风险提示，当前 ${riskAlertCount > 0 ? riskAlertCount : issueCount} 项`}
          onClick={() => setRiskModalOpen(true)}
        >
          <div>
            <span>风险提示</span>
            <strong>{riskAlertCount > 0 ? `${riskAlertCount}项` : issueCount === 0 ? "0项" : `${issueCount}项`}</strong>
          </div>
          <ShieldAlert size={24} aria-hidden="true" />
          <small>{riskAlertCount > 0 ? "全市场 ST / 退市风险清单" : `当前覆盖股票数 ${formatCompact(coverageSymbols)}`}</small>
        </button>
      </section>
      <div className="workspace">
        <StrategyWorkbench
          coverage={coverage}
          settings={settings}
          strategy={strategy}
          onSettingsChange={handleSettingsChange}
          onStrategyChange={setStrategy}
          disabled={isRunningBacktest}
          conditionValidation={conditionValidation}
          isValidatingCondition={isValidatingCondition}
          validationExamples={conditionValidation?.examples ?? []}
          recommendedStrategies={recommendedStrategies}
          savedStrategies={savedStrategies}
          isMutatingStrategies={isMutatingStrategies}
          strategySaveMessage={strategySaveMessage}
          pendingStrategySaveName={pendingStrategySave?.name ?? null}
          onValidateCondition={handleValidateCondition}
          validateConditionText={validateConditionText}
          onApplySavedStrategy={applySavedStrategy}
          onDeleteSavedStrategy={deleteSavedStrategy}
          onConfirmPendingStrategySave={confirmPendingStrategySave}
          onDismissPendingStrategySave={dismissPendingStrategySave}
          onSettingsDraftErrorsChange={setSettingsDraftErrors}
          stockSymbolValidation={stockSymbolValidation}
          isValidatingStockSymbols={isValidatingStockSymbols}
          onValidateStockSymbols={validateCustomStockSymbols}
        />
        {error ? <div className="error-banner" role="alert">{error}</div> : null}
        <div className="results-trades-grid">
          <Suspense fallback={(
            <section className="surface results-surface" aria-busy="true">
              <h2>收益概览</h2>
            </section>
          )}>
            <ResultsOverview
              result={result}
              isRunning={isRunningBacktest}
              phases={runPhases}
              progressMessage={runProgressMessage}
              onRun={runBacktest}
              riskAlertCount={riskAlertCount}
              onOpenRiskAlerts={() => setRiskModalOpen(true)}
            />
          </Suspense>
          <TradesTable trades={isRunningBacktest ? streamedTrades : visibleTrades} />
        </div>
        <DataCenter
          cacheDir=".astock-cache"
          coverage={coverage}
          onCoverageChange={handleCoverageChange}
          onServiceReady={setDataService}
        />
      </div>
      <RiskAlertsModal
        open={riskModalOpen}
        alerts={riskAlerts}
        isLoading={isLoadingRiskAlerts}
        onClose={() => setRiskModalOpen(false)}
        onRefresh={refreshRiskAlerts}
      />
    </main>
  );
}
