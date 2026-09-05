/** Append a supplied company name while preserving the issuer used for filtering. */
export function companyLabel(issuer: string, issuerName?: string | null): string {
  const name = issuerName?.trim();
  return name && name.toLowerCase() !== issuer.toLowerCase()
    ? `${issuer} · ${name}`
    : issuer;
}
