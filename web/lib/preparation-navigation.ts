export type PreparationTarget = 1 | 2 | 3 | 4 | "setup";

/** A typed missing artifact leads to acquisition; other failures require diagnosis. */
export function preparationErrorTarget(code?: string | null): PreparationTarget {
  return code === "source_missing" || code === "sourcemissingerror" ? 1 : "setup";
}
