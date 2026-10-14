import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/* Design §11 sweep (plan 4.18): the focus-ring guarantee and the WCAG
   contrast audit live here as executable evidence. Status/severity colour
   is text-asserted in camera.spec ("Live"/"Offline") and events-log.spec
   (badge always carries its severity word); reduced-motion and the
   aria-live region are asserted in shell.spec. */

const css = readFileSync("src/style.css", "utf8");

/**
 * Parse the `:root` palette out of style.css (name → hex value).
 * @returns {object} token name (with `--`) to hex string
 */
function palette() {
  const start = css.indexOf(":root {");
  const block = css.slice(start, css.indexOf("}", start));
  const out = {};
  for (const match of block.matchAll(
    /(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g,
  )) {
    out[match[1]] = match[2];
  }
  return out;
}

/**
 * sRGB channel → linear light (WCAG 2.x relative luminance step).
 * @param {number} value 0–255 channel value
 * @returns {number} linearised channel
 */
function channel(value) {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/**
 * WCAG 2.x relative luminance of a hex colour.
 * @param {string} hex `#rgb` or `#rrggbb`
 * @returns {number} luminance 0–1
 */
function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  return (
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255)
  );
}

/**
 * Contrast ratio of two hex colours (1–21).
 * @param {string} a first colour
 * @param {string} b second colour
 * @returns {number} ratio
 */
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Real foreground/background token pairs used as body text (≥ 4.5:1). */
const TEXT_PAIRS = [
  ["--text-primary", "--bg-base"],
  ["--text-primary", "--bg-surface"],
  ["--text-primary", "--bg-raised"],
  ["--text-secondary", "--bg-base"],
  ["--text-secondary", "--bg-surface"],
  ["--text-secondary", "--bg-raised"],
  ["--text-muted", "--bg-base"],
  ["--text-muted", "--bg-surface"],
  ["--text-muted", "--bg-raised"],
  ["--accent", "--bg-base"],
  ["--accent", "--bg-surface"],
  ["--accent", "--bg-raised"],
  ["--alert-critical", "--bg-base"],
  ["--alert-critical", "--bg-surface"],
  ["--alert-critical", "--bg-raised"],
  ["--alert-warning", "--bg-base"],
  ["--alert-warning", "--bg-surface"],
  ["--alert-success", "--bg-base"],
  ["--alert-success", "--bg-surface"],
  ["#ffffff", "--accent-fill"],
  ["#ffffff", "--accent-fill-hover"],
  ["#ffffff", "--alert-critical-fill"],
];

/** Meaningful indicators — focus ring states (≥ 3:1, WCAG 1.4.11). */
const UI_PAIRS = [
  ["--accent", "--bg-base"],
  ["--accent", "--bg-surface"],
  ["--accent", "--bg-raised"],
];

/**
 * Resolve a token name or literal hex against the parsed palette.
 * @param {string} key token name (`--x`) or `#hex`
 * @param {object} tokens parsed palette
 * @returns {string} hex value
 */
function resolve(key, tokens) {
  return key.startsWith("--") ? tokens[key] : key;
}

describe("design §11 — focus visibility", () => {
  it("every interactive element gets the accent ring, 2px with 2px offset", () => {
    expect(css).toContain(":focus-visible");
    expect(css).toMatch(/outline:\s*2px solid var\(--accent\)/);
    expect(css).toMatch(/outline-offset:\s*2px/);
  });
});

describe("design §11 — WCAG 2.1 AA contrast audit", () => {
  it("every real text pair meets 4.5:1", () => {
    const tokens = palette();
    for (const [fg, bg] of TEXT_PAIRS) {
      const ratio = contrast(resolve(fg, tokens), resolve(bg, tokens));
      expect(
        ratio,
        `${fg} on ${bg} = ${ratio.toFixed(2)}:1 (need 4.5)`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("focus-ring states meet 3:1 against their grounds", () => {
    const tokens = palette();
    for (const [fg, bg] of UI_PAIRS) {
      const ratio = contrast(resolve(fg, tokens), resolve(bg, tokens));
      expect(
        ratio,
        `${fg} on ${bg} = ${ratio.toFixed(2)}:1 (need 3)`,
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it("parses every token the audit names (no silent misses)", () => {
    const tokens = palette();
    for (const [fg, bg] of [...TEXT_PAIRS, ...UI_PAIRS]) {
      for (const key of [fg, bg]) {
        if (key.startsWith("--")) {
          expect(tokens[key], `unparsed ${key}`).toMatch(/^#[0-9a-fA-F]{3,8}$/);
        }
      }
    }
  });
});
