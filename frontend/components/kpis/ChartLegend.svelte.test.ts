import { describe, it, expect } from "vitest";
import { flushSync, mount } from "svelte";
import ChartLegend from "./ChartLegend.svelte";

const series = [
  { key: "MuckRock", color: "#2a78d6" },
  { key: "DocumentCloud", color: "#eb6834" },
];

function setup() {
  const target = document.createElement("div");
  const props = $state({ series, highlighted: null as string | null });
  mount(ChartLegend, { target, props });
  const [muckrock, documentcloud] = target.querySelectorAll("button");
  return { props, muckrock, documentcloud };
}

describe("ChartLegend", () => {
  it("highlights the series whose entry is clicked", () => {
    const { props, muckrock, documentcloud } = setup();

    muckrock.click();
    flushSync();

    expect(props.highlighted).toBe("MuckRock");
    expect(muckrock.getAttribute("aria-pressed")).toBe("true");
    expect(documentcloud.getAttribute("aria-pressed")).toBe("false");
    expect(documentcloud.classList.contains("dimmed")).toBe(true);
  });

  it("clears the highlight when the same entry is clicked again", () => {
    const { props, muckrock } = setup();

    muckrock.click();
    muckrock.click();
    flushSync();

    expect(props.highlighted).toBeNull();
    expect(muckrock.getAttribute("aria-pressed")).toBe("false");
  });

  it("moves the highlight to another entry", () => {
    const { props, muckrock, documentcloud } = setup();

    muckrock.click();
    documentcloud.click();
    flushSync();

    expect(props.highlighted).toBe("DocumentCloud");
  });
});
