/** Text-only deployment label derived from the page host; never a selectable control. */
export function deploymentLabel(hostname: string): "DEV" | "PROD" {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return normalized === "localhost"
    || normalized === "127.0.0.1"
    || normalized === "::1"
    || normalized.endsWith(".localhost")
    ? "DEV"
    : "PROD";
}
