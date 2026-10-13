import { describe, expect, it } from "vitest";

import {
  coveragePct,
  fromPixels,
  minAreaPx,
  pointInPolygon,
  toPixels,
} from "../roi/geometry.js";

const UNIT_SQUARE = [
  [0, 0],
  [1, 0],
  [1, 1],
  [0, 1],
];

const HALF_WIDTH = [
  [0, 0],
  [0.5, 0],
  [0.5, 1],
  [0, 1],
];

describe("geometry.toPixels / fromPixels", () => {
  it("round-trips a normalised point through pixel space within 1e-9", () => {
    const pt = [0.25, 0.75];
    const px = toPixels(pt, 1920, 1080);
    expect(px[0]).toBeCloseTo(480, 9);
    expect(px[1]).toBeCloseTo(810, 9);
    const back = fromPixels(px, 1920, 1080);
    expect(back[0]).toBeCloseTo(pt[0], 9);
    expect(back[1]).toBeCloseTo(pt[1], 9);
  });

  it("clamps out-of-range values to [0,1]", () => {
    const clamped = fromPixels([-50, 5000], 100, 100);
    expect(clamped[0]).toBe(0);
    expect(clamped[1]).toBe(1);
    const px = toPixels([-0.5, 1.5], 100, 100);
    expect(px[0]).toBe(0);
    expect(px[1]).toBe(100);
  });
});

describe("geometry.coveragePct", () => {
  it("unit square covers 100%", () => {
    expect(coveragePct(UNIT_SQUARE)).toBe(100);
  });

  it("half-width quad covers 50%", () => {
    expect(coveragePct(HALF_WIDTH)).toBe(50);
  });

  it("triangle covering a quarter of the frame", () => {
    const tri = [
      [0, 0],
      [1, 0],
      [0, 1],
    ];
    expect(coveragePct(tri)).toBeCloseTo(50, 1);
  });

  it("degenerate polygon (<3 points) is 0", () => {
    expect(coveragePct([[0, 0]])).toBe(0);
  });
});

describe("geometry.minAreaPx", () => {
  it("unit square at 640x360 exceeds the 500px² floor", () => {
    expect(minAreaPx(UNIT_SQUARE, 640, 360)).toBe(640 * 360);
  });

  it("tiny triangle is under the floor", () => {
    const tiny = [
      [0.01, 0.01],
      [0.012, 0.01],
      [0.011, 0.012],
    ];
    expect(minAreaPx(tiny, 1920, 1080)).toBeLessThan(500);
  });

  it("degenerate polygon is 0", () => {
    expect(minAreaPx(HALF_WIDTH.slice(0, 2), 640, 360)).toBe(0);
  });
});

describe("geometry.pointInPolygon (edge-inclusive, matches backend roi.py)", () => {
  it("interior point is inside", () => {
    expect(pointInPolygon([0.5, 0.5], UNIT_SQUARE)).toBe(true);
  });

  it("exterior point is outside", () => {
    expect(pointInPolygon([1.5, 0.5], UNIT_SQUARE)).toBe(false);
  });

  it("point exactly on an edge counts as inside", () => {
    expect(pointInPolygon([0, 0.5], UNIT_SQUARE)).toBe(true);
    expect(pointInPolygon([0.5, 0], UNIT_SQUARE)).toBe(true);
  });

  it("point exactly on a vertex counts as inside", () => {
    expect(pointInPolygon([1, 1], UNIT_SQUARE)).toBe(true);
  });

  it("polygon with fewer than 3 points never contains", () => {
    expect(pointInPolygon([0.5, 0.5], UNIT_SQUARE.slice(0, 2))).toBe(false);
  });
});
