import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = join(process.cwd(), "src");
const files = (directory: string): string[] => readdirSync(directory).flatMap((name) => {
  const path = join(directory, name);
  return statSync(path).isDirectory() ? files(path) : /\.(css|tsx)$/.test(path) ? [path] : [];
});
const expand = (hex: string) => hex.length <= 4
  ? hex.slice(1).split("").slice(0, 3).map((digit) => parseInt(digit + digit, 16))
  : [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map((pair) => parseInt(pair, 16));
const chromaticFunctions = (source: string) => [
  ...source.matchAll(/rgba?\(\s*(\d+)\D+(\d+)\D+(\d+)/gi),
].filter((match) => new Set(match.slice(1, 4).map(Number)).size !== 1).map((match) => match[0]);
const chromaticHsl = (source: string) => [...source.matchAll(/hsla?\(\s*[^, ]+[, ]+([\d.]+)%/gi)]
  .filter((match) => Number(match[1]) !== 0).map((match) => match[0]);
const chromaticNames = /\b(red|blue|green|orange|purple|yellow|teal|navy|maroon|olive|aqua|fuchsia)\b/gi;

describe("monochrome UI policy", () => {
  it("contains no chromatic hex values or gradients", () => {
    const violations = files(sourceRoot).flatMap((path) => {
      const source = readFileSync(path, "utf8");
      const hexes = source.match(/#[0-9a-f]{3,8}\b/gi) ?? [];
      const chromatic = hexes.filter((hex) => new Set(expand(hex)).size !== 1);
      return [...chromatic, ...chromaticFunctions(source), ...chromaticHsl(source), ...(source.match(chromaticNames) ?? []), ...(source.match(/(?:linear|radial|conic)-gradient\(/gi) ?? [])]
        .map((value) => `${path.replace(process.cwd(), "")}: ${value}`);
    });
    expect(violations).toEqual([]);
  });
});
