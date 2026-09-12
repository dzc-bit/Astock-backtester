import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import type { AiEquityPoint } from "../aiTypes";

type Props = {
  title: string;
  points: AiEquityPoint[];
};

/**
 * ECharts rendering of a backtest equity curve (equity + drawdown) inside the
 * AI drawer. echarts.init is guarded so jsdom-based tests render the container
 * without a canvas backend.
 */
export function AiEquityChart({ title, points }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    try {
      chartRef.current = echarts.init(containerRef.current);
    } catch {
      // jsdom / 无 canvas 环境：容器仍渲染，仅无图形
      return;
    }
    const observer = new ResizeObserver(() => chartRef.current?.resize());
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || points.length === 0) {
      return;
    }
    chart.setOption({
      title: { text: title, left: 4, top: 2, textStyle: { fontSize: 12, fontWeight: 600, color: "#44506b" } },
      tooltip: { trigger: "axis", textStyle: { fontSize: 11 } },
      legend: { data: ["权益", "回撤"], top: 20, right: 4, textStyle: { fontSize: 11 } },
      grid: { left: 52, right: 44, top: 48, bottom: 24 },
      xAxis: {
        type: "category",
        data: points.map((point) => point.trade_date),
        axisLabel: { fontSize: 10, interval: Math.max(0, Math.floor(points.length / 6)) }
      },
      yAxis: [
        { type: "value", scale: true, axisLabel: { fontSize: 10 } },
        {
          type: "value",
          axisLabel: { fontSize: 10, formatter: (value: number) => `${(value * 100).toFixed(0)}%` }
        }
      ],
      series: [
        {
          name: "权益",
          type: "line",
          data: points.map((point) => point.equity),
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, color: "#0f766e" },
          areaStyle: { opacity: 0.06, color: "#0f766e" }
        },
        {
          name: "回撤",
          type: "line",
          yAxisIndex: 1,
          data: points.map((point) => point.drawdown_pct),
          showSymbol: false,
          lineStyle: { width: 1, color: "#d92d20", type: "dashed" }
        }
      ]
    });
  }, [points, title]);

  return <div ref={containerRef} className="ai-chart" role="img" aria-label={title} />;
}
