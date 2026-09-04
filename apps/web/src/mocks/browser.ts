import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

const worker = setupWorker(...handlers);

let startPromise: ReturnType<typeof worker.start> | null = null;

export function startMockWorker() {
  startPromise ??= worker.start({ onUnhandledRequest: "bypass" });
  return startPromise;
}
