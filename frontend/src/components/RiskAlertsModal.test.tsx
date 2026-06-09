import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RiskAlertsModal } from "./RiskAlertsModal";

it("shows successful risk results first and keeps source failures in diagnostics", () => {
  render(
    <RiskAlertsModal
      open
      alerts={{
        updated_at: "2026-06-07T10:00:00+08:00",
        source: "local-watchlist",
        diagnostics: [
          "本地风险兜底读取失败：Could not open Parquet input source '<Buffer>'",
          "东方财富风险源不可用，已使用本地 ST 字段兜底。",
          "实时扫描未发现新增已 ST、*ST 或退市名称变化。"
        ],
        items: [
          {
            symbol: "000716",
            name: "黑芝麻",
            risk_type: "本地观察名单",
            reason: "已加载本地潜在风险观察名单。",
            severity: "medium",
            source: "local-watchlist",
            detected_at: "2026-06-07T10:00:00+08:00"
          }
        ]
      }}
      isLoading={false}
      onClose={vi.fn()}
      onRefresh={vi.fn()}
    />
  );

  expect(screen.getByText("已加载本地风险观察名单 1 只，实时扫描完成。")).toBeInTheDocument();
  expect(screen.getByText("黑芝麻")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "刷新风险" })).toBeInTheDocument();
  expect(screen.getByText("辅助数据源诊断")).toBeInTheDocument();
});
