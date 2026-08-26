import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = join(process.cwd(), "src");
const legacyDesignLayers = new Set(["crouwel.css", "weingart.css"]);
const files = (directory: string): string[] => readdirSync(directory).flatMap((name) => {
  const path = join(directory, name);
  return statSync(path).isDirectory() ? files(path) : /\.(css|tsx)$/.test(path) && !legacyDesignLayers.has(name) ? [path] : [];
});

describe("Peer Design system", () => {
  it("loads the Peer runtime layer and disconnects legacy design layers", () => {
    const designLayer = readFileSync(join(sourceRoot, "app/globals.css"), "utf8");
    const layout = readFileSync(join(sourceRoot, "app/layout.tsx"), "utf8");
    expect(designLayer).toContain("--peer-color-canvas:");
    expect(designLayer).toContain("--peer-color-accent:");
    expect(layout).toContain('import "./base-ui.css"');
    expect(layout).not.toMatch(/crouwel\.css|weingart\.css/);
  });

  it("keeps the shared Peer control, spacing, radius, and typography contracts", () => {
    const globals = readFileSync(join(sourceRoot, "app/globals.css"), "utf8");
    expect(globals).toContain("--peer-control-height: 2rem");
    expect(globals).toContain("--peer-space-4: 1rem");
    expect(globals).toContain("--peer-radius: 0");
    expect(globals).toContain("--peer-radius-round: 100%");
    expect(globals).toContain("--peer-font-sans:");
    expect(globals).not.toMatch(/\*[^}]*border-radius:\s*0\s*!important/s);
  });

  it("uses opaque design tokens and Base UI-backed buttons", () => {
    const runtimeSource = files(sourceRoot).map((path) => readFileSync(path, "utf8")).join("\n");
    expect(runtimeSource).not.toMatch(/color-mix\(/i);
    expect(runtimeSource).not.toMatch(/background(?:-color|Color)?\s*[:=]\s*["']?var\(--(?:red|blue)\)/i);
    expect(runtimeSource).not.toMatch(/<button\b/);
  });
});
