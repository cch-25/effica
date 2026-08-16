import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = join(process.cwd(), "src");
const legacyDesignLayers = new Set(["crouwel.css", "weingart.css"]);
const files = (directory: string): string[] => readdirSync(directory).flatMap((name) => {
  const path = join(directory, name);
  return statSync(path).isDirectory() ? files(path) : /\.(css|tsx)$/.test(path) && !legacyDesignLayers.has(name) ? [path] : [];
});

const expand = (hex: string) => hex.length <= 4
  ? hex.slice(1).split("").slice(0, 3).map((digit) => parseInt(digit + digit, 16))
  : [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map((pair) => parseInt(pair, 16));

const allowedSignalColors = new Set(["#0047ff", "#d40000"]);
const chromaticRgb = (source: string) => [...source.matchAll(/rgba?\(\s*(\d+)\D+(\d+)\D+(\d+)/gi)]
  .filter((match) => new Set(match.slice(1, 4).map(Number)).size !== 1)
  .map((match) => match[0]);

describe("square Base UI color system", () => {
  it("keeps every runtime chromatic value within the red and blue text palette", () => {
    const violations = files(sourceRoot).flatMap((path) => {
      const source = readFileSync(path, "utf8");
      const chromatic = (source.match(/#[0-9a-f]{3,8}\b/gi) ?? [])
        .filter((hex) => new Set(expand(hex)).size !== 1)
        .filter((hex) => !allowedSignalColors.has(hex.toLowerCase()));
      return [...chromatic, ...chromaticRgb(source)].map((value) => `${path.replace(process.cwd(), "")}: ${value}`);
    });

    expect(violations).toEqual([]);
  });

  it("reserves red and blue for text instead of surfaces", () => {
    const runtimeSource = files(sourceRoot).map((path) => readFileSync(path, "utf8")).join("\n");
    expect(runtimeSource).not.toMatch(/color-mix\(/i);
    expect(runtimeSource).not.toMatch(/background(?:-color|Color)?\s*[:=]\s*["']?var\(--(?:red|blue)\)/i);
  });

  it("defines the signal palette once and disconnects the legacy design layers", () => {
    const designLayer = readFileSync(join(sourceRoot, "app/globals.css"), "utf8");
    const layout = readFileSync(join(sourceRoot, "app/layout.tsx"), "utf8");
    for (const color of allowedSignalColors) {
      expect(designLayer.match(new RegExp(color, "gi"))).toHaveLength(1);
    }
    expect(layout).toContain('import "./base-ui.css"');
    expect(layout).not.toMatch(/crouwel\.css|weingart\.css/);
  });

  it("enforces zero radius and Base UI-backed buttons", () => {
    const globals = readFileSync(join(sourceRoot, "app/globals.css"), "utf8");
    const runtimeSource = files(sourceRoot).map((path) => readFileSync(path, "utf8")).join("\n");
    expect(globals).toContain("--radius-sm: 0");
    expect(globals).toContain("--radius: 0");
    expect(globals).toMatch(/\* \{[^}]*border-radius: 0 !important/s);
    expect(runtimeSource).not.toMatch(/<button\b/);
  });
});
