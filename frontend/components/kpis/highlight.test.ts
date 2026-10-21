import { describe, it, expect } from "vitest";
import { type SeriesHighlight, pinHighlight } from "./highlight";

// Mirrors LayerChart's SeriesState: every change notifies onHighlightChange.
function seriesState(): SeriesHighlight {
  return {
    highlightKey: null,
    onHighlightChange: undefined,
    setHighlight(key) {
      this.highlightKey = key;
      this.onHighlightChange?.();
    },
  };
}

describe("pinHighlight", () => {
  it("keeps a selected series highlighted when hover clears it", () => {
    const series = seriesState();
    pinHighlight(series, "DocumentCloud");

    series.setHighlight(null);

    expect(series.highlightKey).toBe("DocumentCloud");
  });

  it("keeps a selected series highlighted when another is hovered", () => {
    const series = seriesState();
    pinHighlight(series, "DocumentCloud");

    series.setHighlight("MuckRock");

    expect(series.highlightKey).toBe("DocumentCloud");
  });

  it("hands highlighting back to hover once the selection clears", () => {
    const series = seriesState();
    pinHighlight(series, "DocumentCloud");
    pinHighlight(series, null);

    series.setHighlight("MuckRock");
    expect(series.highlightKey).toBe("MuckRock");
    series.setHighlight(null);
    expect(series.highlightKey).toBeNull();
  });
});
