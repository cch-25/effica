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

const allowedSignalColors = new Set(["#2457e6", "#ef3e33", "#f4cb38"]);
const chromaticRgb = (source: string) => [...source.matchAll(/rgba?\(\s*(\d+)\D+(\d+)\D+(\d+)/gi)]
  .filter((match) => new Set(match.slice(1, 4).map(Number)).size !== 1)
  .map((match) => match[0]);

describe("restrained Crouwel color system", () => {
  it("keeps every chromatic hex within the three-color signal palette", () => {
    const violations = files(sourceRoot).flatMap((path) => {
      const source = readFileSync(path, "utf8");
      const chromatic = (source.match(/#[0-9a-f]{3,8}\b/gi) ?? [])
        .filter((hex) => new Set(expand(hex)).size !== 1)
        .filter((hex) => !allowedSignalColors.has(hex.toLowerCase()));
      return [...chromatic, ...chromaticRgb(source)].map((value) => `${path.replace(process.cwd(), "")}: ${value}`);
    });

    expect(violations).toEqual([]);
  });

  it("defines the signal palette once in the shared design layer", () => {
    const designLayer = readFileSync(join(sourceRoot, "app/crouwel.css"), "utf8");
    for (const color of allowedSignalColors) {
      expect(designLayer.match(new RegExp(color, "gi"))).toHaveLength(1);
    }
  });
});
