/**
 * Typed API client.
 *
 * `schema.d.ts` is generated from the backend's OpenAPI document (`npm run api:sync`), so every
 * path, parameter and response below is type-checked against the real API: if the backend
 * changes a field, this code stops compiling instead of failing for users.
 *
 * Authentication is the HttpOnly session cookie, which the browser sends automatically and
 * JavaScript can never read. There are no tokens in this code.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export const api = createClient<paths>({
  // Absolute URL from the current origin: identical in the browser, and also valid in tests
  // (Node's fetch rejects relative URLs).
  baseUrl: new URL("/api", window.location.origin).href,
  credentials: "same-origin",
  // Repeated query parameters (?industry=a&industry=b), which is what FastAPI expects.
  querySerializer: { array: { style: "form", explode: true } },
  // Look up fetch at call time rather than capturing it at import time, so tools that wrap the
  // global fetch after startup (the test suite's API simulator, monitoring) are respected.
  fetch: (request) => globalThis.fetch(request),
});

export interface FieldError {
  field: string;
  message: string;
}

/** An error response from the API, in the backend's standard error shape. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown[];

  constructor(status: number, body: unknown) {
    const error = (body as { error?: Record<string, unknown> } | undefined)?.error ?? {};
    const message = typeof error.message === "string" ? error.message : "Something went wrong.";
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = typeof error.code === "string" ? error.code : "unknown_error";
    this.requestId = typeof error.request_id === "string" ? error.request_id : null;
    this.details = Array.isArray(error.details) ? error.details : [];
  }

  /** Validation errors as {field, message}, from 422 `details` like {loc: ["body", "email"]}. */
  get fieldErrors(): FieldError[] {
    return this.details.flatMap((detail) => {
      const { loc, msg } = detail as { loc?: unknown[]; msg?: unknown };
      const field = Array.isArray(loc)
        ? loc.filter((p) => typeof p === "string").at(-1)
        : undefined;
      return typeof field === "string" && typeof msg === "string"
        ? [{ field, message: msg.replace(/^Value error, /, "") }]
        : [];
    });
  }
}

interface ApiResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Return the data of a successful call, or throw ApiError (so TanStack Query sees a failure). */
export async function unwrap<T>(call: Promise<ApiResult<T>>): Promise<T> {
  let result: ApiResult<T>;
  try {
    result = await call;
  } catch {
    throw new ApiError(0, {
      error: { code: "network_error", message: "Cannot reach the server. Check your connection." },
    });
  }
  if (!result.response.ok) {
    throw new ApiError(result.response.status, result.error);
  }
  return result.data as T;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
