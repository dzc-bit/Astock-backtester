import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { defaultSettings, defaultStrategy } from "../strategyDefaults";
import { StrategyWorkbench } from "./StrategyWorkbench";

it("shows structured entry and exit writing templates for condition help", async () => {
  const user = userEvent.setup();
  render(
    <StrategyWorkbench
      coverage={[]}
      settings={defaultSettings}
      strategy={defaultStrategy}
      onSettingsChange={() => {}}
      onStrategyChange={() => {}}
      conditionValidation={null}
      validationExamples={[]}
      recommendedStrategies={[]}
      savedStrategies={[]}
      strategySaveMessage={null}
      onValidateCondition={() => {}}
      validateConditionText={vi.fn(async () => ({
        ok: false,
        normalized_text: "",
        condition: null,
        errors: [],
        examples: []
      }))}
      onApplySavedStrategy={() => {}}
      onDeleteSavedStrategy={() => {}}
    />
  );

  // 手工编辑器默认收起：先展开高级模式，再断言模板仍在其中。
  await user.click(screen.getByRole("button", { name: /高级模式/ }));

  expect(screen.getByRole("heading", { name: "可写入能力" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "入场条件模板" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "离场条件模板" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "套用入场条件：收盘价站上20日均线" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "套用离场条件：跌破20日低点" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "套用入场条件：近5日涨幅小于12%" })).not.toBeInTheDocument();
});
