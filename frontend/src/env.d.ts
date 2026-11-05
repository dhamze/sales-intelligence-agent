/// <reference types="vite/client" />

/** Build-time settings (set when building the production image; see deploy/web.Dockerfile). */
interface ImportMetaEnv {
  /** Sentry project address for browser errors. Unset = no error reporting. */
  readonly VITE_SENTRY_DSN?: string;
  /** Version identifier shown in Sentry (the git commit). */
  readonly VITE_RELEASE?: string;
}
