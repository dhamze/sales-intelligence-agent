/**
 * Where to go after login. Only same-site paths are accepted: "/companies?q=x" is fine, but
 * "https://evil.example" or "//evil.example" (protocol-relative) would turn the login page into
 * an "open redirect" that phishing links could abuse.
 */
export function safeRedirect(target: string | undefined): string {
  if (!target || !target.startsWith("/") || target.startsWith("//") || target.includes("\\")) {
    return "/companies";
  }
  return target;
}
