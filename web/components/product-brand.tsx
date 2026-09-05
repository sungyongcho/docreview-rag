import { PRODUCT_ASCII, PRODUCT_MONOGRAM } from "@/branding/ascii";
import "./product-brand.css";

/** Keep the Small wordmark legible by switching to its compact monogram. */
export function ProductBrand({ hero = false }: { hero?: boolean }) {
  return <span className={`product-brand${hero ? " product-brand-hero" : ""}`} role="img" aria-label="DocReview RAG v2">
    <span className="product-brand-lockup" aria-hidden="true">
      {hero && <span className="product-ascii product-ascii-full">{PRODUCT_ASCII}</span>}
      <span className="product-ascii product-ascii-compact">{PRODUCT_MONOGRAM}</span>
      <span className="product-edition">DocReview RAG <b>v2</b></span>
    </span>
  </span>;
}
