import { expect, it } from "vitest";
import { loadSavedStrategies } from "../savedStrategies";

it("keeps built-in local strategy presets even when local storage is empty", () => {
  window.localStorage.removeItem("astock-saved-strategies");

  const saved = loadSavedStrategies();

  expect(saved.some((item) => item.name === "基础均衡策略")).toBe(true);
  expect(saved.some((item) => item.name === "放量突破策略")).toBe(true);
  expect(saved.some((item) => item.name === "回踩均线策略")).toBe(true);
});
