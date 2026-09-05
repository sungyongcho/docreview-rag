export function ProductMark({ className = "" }: { className?: string }) {
  return <svg className={className} viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M10 5h17l8 8-5 22H5L10 5Z" stroke="currentColor" strokeWidth="2.6" strokeLinejoin="round"/><path d="m26 6-2 9h10M12 21h13M10 27h12" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round"/></svg>;
}

export const PRODUCT_ASCII = String.raw`   ___           ___           _              ___  ___  _____
  / _ \___  ____/ _ \___ _  __(_)__ _    __  / _ \/ _ |/ ___/
 / // / _ \/ __/ , _/ -_) |/ / / -_) |/|/ / / , _/ __ / (_ /
/____/\___/\__/_/|_|\__/|___/_/\__/|__,__/ /_/|_/_/ |_\___/`;

/** Preserve the original terminal lettering as selectable, resolution-independent text. */
export function ProductBrand({ hero = false }: { hero?: boolean }) {
  return <span className={`product-brand${hero ? " product-brand-hero" : ""}`} role="img" aria-label="DocReview RAG v2"><span className="product-ascii" aria-hidden="true">{PRODUCT_ASCII}</span><span className="product-edition" aria-hidden="true">DOCREVIEW RAG <b>v2</b></span></span>;
}
