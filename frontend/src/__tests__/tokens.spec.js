import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/* Vitest runs from the frontend package root (npm script / CI working
   directory), and import.meta.url is not a file: URL under jsdom. */
const styleCss = readFileSync("src/style.css", "utf8");

/**
 * Every source module under src/ (style.css holds the only allowed hex;
 * the tests themselves contain hex regexes and are skipped).
 * @param {string} dir directory to walk
 * @returns {string[]} absolute-ish paths of .vue/.js files
 */
function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      return name === "__tests__" ? [] : walk(full);
    }
    return name.endsWith(".vue") || name.endsWith(".js") ? [full] : [];
  });
}

describe("design §2 tokens", () => {
  it("declares every palette token in :root", () => {
    const palette = [
      "--bg-base",
      "--bg-surface",
      "--bg-raised",
      "--border",
      "--text-primary",
      "--text-secondary",
      "--text-muted",
      "--accent",
      "--accent-hover",
      "--accent-fill",
      "--accent-fill-hover",
      "--alert-critical",
      "--alert-critical-fill",
      "--alert-warning",
      "--alert-success",
      "--roi-fill",
      "--roi-stroke",
      "--detect-box",
    ];
    for (const token of palette) {
      expect(styleCss, `missing ${token}`).toMatch(
        new RegExp(`\\s${token}:\\s*#[0-9a-fA-F]{3,8}\\s*;`),
      );
    }
  });

  it("declares radius and motion tokens", () => {
    for (const token of [
      "--radius-control: 6px",
      "--radius-card: 10px",
      "--radius-pill: 999px",
      "--dur-fast: 120ms",
      "--dur-base: 150ms",
      "--dur-slow: 300ms",
      "--dur-alert: 400ms",
      "--ease: cubic-bezier(0.2, 0, 0, 1)",
    ]) {
      expect(styleCss, `missing ${token}`).toContain(token);
    }
  });

  it("maps colours through var() in @theme, never a second hex literal", () => {
    const theme = styleCss.slice(styleCss.indexOf("@theme"));
    expect(theme).toContain("--color-bg-base: var(--bg-base)");
    expect(theme).toContain("--color-alert-critical: var(--alert-critical)");
    expect(theme).not.toMatch(/--color-[a-z-]+:\s*#/);
  });
});

describe("no hardcoded hex outside the token file", () => {
  it("every component and module is hex-free", () => {
    const files = walk("src");
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      const source = readFileSync(file, "utf8");
      expect(source, `${file} contains a hardcoded hex`).not.toMatch(
        /#[0-9a-fA-F]{3,8}\b/,
      );
    }
  });
});
