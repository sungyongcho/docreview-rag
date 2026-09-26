import { notFound } from "next/navigation";
import { DocumentationPage } from "@/components/documentation-page";
import { DOCUMENTS, developmentStoryDocument } from "@/lib/documentation-registry.mjs";

const routedDocuments = [...DOCUMENTS, developmentStoryDocument("ko"), developmentStoryDocument("en")];

export const dynamicParams = false;

/** The locale root pages (no slug) have their own routes; the registry supplies every slugged route. */
export function generateStaticParams() {
  return routedDocuments.filter((document) => document.slug).map(({ locale, slug }) => ({ locale, slug }));
}

type Parameters = { params: Promise<{ locale: string; slug: string }> };

export async function generateMetadata({ params }: Parameters) {
  const { locale, slug } = await params;
  const document = routedDocuments.find((item) => item.locale === locale && item.slug === slug);
  if (!document) notFound();
  const title = `${document.title} | DocReview RAG`;
  // The CLI reference used to be a static page that kept the site-wide description; keep its head unchanged.
  if (document.id === "cli") return { title };
  return { title, description: document.summary };
}

export default async function Page({ params }: Parameters) {
  const { locale, slug } = await params;
  const document = routedDocuments.find((item) => item.locale === locale && item.slug === slug);
  if (!document) notFound();
  return <DocumentationPage documentId={document.id} locale={document.locale} />;
}
