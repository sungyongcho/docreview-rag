/** Display the server's selected environment, including local production previews. */
export function deploymentLabel(environment?: "dev" | "prod"): "DEV" | "PROD" | "Checking mode…" {
  return environment === "dev" ? "DEV" : environment === "prod" ? "PROD" : "Checking mode…";
}
