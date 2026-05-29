import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { defaultSettings, defaultStrategy } from "../strategyDefaults";
import { StrategyWorkbench } from "./StrategyWorkbench";

it("shows structured entry and exit writing templates for condition help", () => {
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

  expect(screen.getByRole("heading", { name: "入场条件写法模板" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "离场条件写法模板" })).toBeInTheDocument();
  expect(screen.getByText("收盘价站上N日均线")).toBeInTheDocument();
  expect(screen.getByText("跌破N日低点")).toBeInTheDocument();
  expect(screen.getByText("写不出来时，先照着模板替换数字，再点校验条件。")).toBeInTheDocument();
});
