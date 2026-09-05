"use client";

import { ArrowUpRight } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { ProductBrand } from "@/components/product-brand";

/** One quiet creator identity shared by the product, documentation, and About screen. */
export function CreatorSignature({ variant = "compact" }: { variant?: "compact" | "footer" | "about" }) {
  const { t } = useI18n();
  return <div className={`creator-signature creator-signature-${variant}`}>
    {variant === "about" && <ProductBrand hero />}
    <a href="https://sungyongcho.com" target="_blank" rel="noopener noreferrer" aria-label={t("Sungyong Cho · portfolio (opens in a new tab)")}>
      <span>{t(variant === "about" ? "Designed & built by" : "Built by")} <strong>Sungyong Cho</strong><ArrowUpRight size={13} aria-hidden="true" /></span>
      <small>sungyongcho.com</small>
    </a>
  </div>;
}
