import { render, screen } from "@testing-library/react";
import { App } from "../App";

describe("Backtester UI", () => {
  it("renders the five first-version work areas", async () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Data Center" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Strategy Editor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Backtest Settings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Result Overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Trade Explanations" })).toBeInTheDocument();
  });

  it("exposes market cap and capital flow conditions", () => {
    render(<App />);

    expect(screen.getByText("Float market cap range")).toBeInTheDocument();
    expect(screen.getByText("N-day main net inflow")).toBeInTheDocument();
  });
});
