/** Localize registered portfolio company names, including code-prefixed facet labels. */
export function companyDisplayName(name: string, locale: string): string {
  const names = [
    { en: "Samsung Electronics", ko: "삼성전자", aliases: ["삼성전자", "samsung electronics"] },
    { en: "SK hynix", ko: "SK하이닉스", aliases: ["sk하이닉스", "sk 하이닉스", "sk hynix"] },
  ];
  const parts = name.split(" · ").map(part => {
    if (locale !== "ko" && part.trim() === "엔비디아") return "NVIDIA";
    const entry = names.find(company => company.aliases.includes(part.trim().toLowerCase()));
    return entry ? (locale === "ko" ? entry.ko : entry.en) : part;
  });
  return [...new Set(parts)].join(" · ");
}

/** Append a supplied company name while preserving the issuer used for filtering. */
export function companyLabel(issuer: string, issuerName?: string | null, locale?: string): string {
  const name = locale ? companyDisplayName(issuerName?.trim() ?? "", locale) : issuerName?.trim();
  return name && name.toLowerCase() !== issuer.toLowerCase()
    ? `${issuer} · ${name}`
    : issuer;
}
