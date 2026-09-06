/** Clear and verify only this origin's DocReview data; preserve unrelated storage. */
export function clearExtremeBrowserData(...stores: Storage[]): void {
  for (const store of stores) {
    const owned = (key: string | null) => Boolean(key?.startsWith("docreview:") || key?.startsWith("docreview."));
    const keys = Array.from({ length: store.length }, (_, index) => store.key(index)).filter((key): key is string => key !== null && owned(key));
    keys.forEach((key) => store.removeItem(key));
    if (Array.from({ length: store.length }, (_, index) => store.key(index)).some(owned)) {
      throw new Error("DocReview browser storage deletion is incomplete.");
    }
  }
}
