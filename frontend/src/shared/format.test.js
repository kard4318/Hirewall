import { describe, expect, it } from "vitest";
import { count, date, decimal, deltaPts, groupSize, percent, quarter, ratio, signed } from "./format.js";

describe("format", () => {
  it("quarters", () => {
    expect(quarter("2026Q3")).toBe("Q3 2026");
    expect(quarter("2026Q3", { short: true })).toBe("Q3 ’26");
    expect(quarter("2026Q4*")).toBe("Q4 2026*");
    expect(quarter("Spring")).toBe("Spring");
  });
  it("ratios and percents", () => {
    expect(ratio(3.94)).toBe("3.9×");
    expect(percent(0.253)).toBe("25.3%");
    expect(percent(0.5, 0)).toBe("50%");
    expect(percent(null)).toBe("–");
  });
  it("deltas use points and a true minus sign", () => {
    expect(deltaPts(0.012)).toBe("+1.2 pts");
    expect(deltaPts(-0.004)).toBe("−0.4 pts");
    expect(deltaPts(0.0001)).toBe("0.0 pts");
    expect(signed(-1.25, 1, " y")).toBe("−1.3 y");
  });
  it("counts and group sizes", () => {
    expect(count(1234)).toBe("1,234");
    expect(decimal(3.456)).toBe("3.5");
    expect(groupSize(77)).toBe("n = 77");
  });
  it("dates", () => {
    expect(date("2026-06-04")).toBe("4 Jun 2026");
    expect(date("2026-06-04", { withYear: false })).toBe("4 Jun");
    expect(date("nope")).toBe("–");
  });
  it("never prints glyphs missing from the bundled fonts", () => {
    const out = [quarter("2026Q1"), ratio(2), percent(0.1), deltaPts(-0.2), groupSize(5), date("2026-01-01")].join(" ");
    expect(out).not.toMatch(/[→←≥≤↑↓]/);
  });
});
