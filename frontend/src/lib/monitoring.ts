/**
 * Browser error reporting with Sentry (only when VITE_SENTRY_DSN was set at build time).
 *
 * Privacy: no user identity, cookies, headers, bodies or query strings; console output is not
 * recorded; URLs in breadcrumbs lose their query string (searches may contain company names).
 * Expected API errors (4xx: validation, not found, logged out) are not reported.
 */
import * as Sentry from "@sentry/react";

import { ApiError } from "@/lib/api/client";

const dsn = import.meta.env.VITE_SENTRY_DSN;

function withoutQuery(url: unknown): unknown {
  return typeof url === "string" ? url.split("?")[0] : url;
}

/** Drop expected API errors; strip the query string from the page URL. */
export function filterEvent<E extends Sentry.ErrorEvent>(
  event: E,
  hint: Sentry.EventHint,
): E | null {
  const error = hint.originalException;
  if (error instanceof ApiError && error.status < 500) return null;
  if (event.request?.url) event.request.url = withoutQuery(event.request.url) as string;
  return event;
}

/** Drop console output; strip query strings from URLs. */
export function filterBreadcrumb(breadcrumb: Sentry.Breadcrumb): Sentry.Breadcrumb | null {
  if (breadcrumb.category === "console") return null;
  if (breadcrumb.data) {
    for (const key of ["url", "from", "to"]) {
      if (key in breadcrumb.data) breadcrumb.data[key] = withoutQuery(breadcrumb.data[key]);
    }
  }
  return breadcrumb;
}

export function initMonitoring(): void {
  if (!dsn) return;
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    release: import.meta.env.VITE_RELEASE,
    tracesSampleRate: 0,
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: false,
      httpBodies: [],
      urlQueryParams: false,
      genAI: { inputs: false, outputs: false },
    },
    beforeSend: filterEvent,
    beforeBreadcrumb: filterBreadcrumb,
  });
}

/** Report an error caught by the app itself (e.g. a route's error boundary). */
export function reportError(error: unknown): void {
  if (dsn) Sentry.captureException(error);
}
