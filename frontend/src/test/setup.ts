import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./server";

// Any request without a handler is blocked (it can never reach a real server) AND fails the
// test: a component silently getting a failed request would otherwise go unnoticed.
const unhandled: string[] = [];

beforeAll(() => {
  server.events.on("request:unhandled", ({ request }) => {
    unhandled.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  server.listen({ onUnhandledFrame: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  const missed = unhandled.splice(0);
  if (missed.length > 0) {
    throw new Error(
      `Unhandled API requests (add MSW handlers): ${[...new Set(missed)].join(", ")}`,
    );
  }
});

afterAll(() => {
  server.close();
});
