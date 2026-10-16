import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

function block(selector: string): Record<string, string> {
  const body = css.split(`${selector} {`)[1].split("}")[0];
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6});/g)].map((m) => [m[1], m[2]]));
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT_PAIRS: [string, string][] = [
  ["fg", "bg"],
  ["fg", "surface"],
  ["fg-muted", "surface"],
  ["fg-muted", "bg"],
  ["on-action", "action"],
  ["on-action", "action-hover"],
  ["nav-fg", "nav-bg"],
  ["nav-fg", "nav-active-bg"],
  ["pass-fg", "pass-bg"],
  ["warn-fg", "warn-bg"],
  ["fail-fg", "fail-bg"],
  ["error-fg", "error-bg"],
  ["neutral-fg", "neutral-bg"],
  ["info-fg", "info-bg"],
];

const light = block(":root");
const themes = { light, dark: { ...light, ...block('[data-theme="dark"]') } };

describe.each(Object.entries(themes))("%s theme text contrast", (_name, tokens) => {
  it.each(TEXT_PAIRS)("--%s on --%s meets WCAG AA 4.5:1", (fg, bg) => {
    expect(contrast(tokens[fg], tokens[bg])).toBeGreaterThanOrEqual(4.5);
  });
});

it("raw brand red is not used for white text (fails AA)", () => {
  expect(contrast("#ffffff", light.brand)).toBeLessThan(4.5);
});
