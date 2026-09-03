import { expect, it } from "vitest";
import { trailingMean } from "./RegimeHistoryChart";
it("uses trailing trading observations without future leakage or changing inputs", () => {
  const scores = [0, 50, 100, 50, 0, 100];
  expect(trailingMean(scores)).toEqual([0, 25, 50, 50, 40, 60]);
  expect(scores).toEqual([0, 50, 100, 50, 0, 100]);
  expect(trailingMean([65])).toEqual([65]);
});
