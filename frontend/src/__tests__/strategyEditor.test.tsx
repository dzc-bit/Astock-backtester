import { render, screen } from "@testing-library/react";
import { App } from "../App";

describe("App shell", () => {
  it("shows active condition count and strategy name", () => {
    render(<App />);

    expect(screen.getByText("A-Stock Backtester")).toBeInTheDocument();
    expect(screen.getByText("3 active conditions")).toBeInTheDocument();
    expect(screen.getByText("Market heat + small cap inflow")).toBeInTheDocument();
  });
});
