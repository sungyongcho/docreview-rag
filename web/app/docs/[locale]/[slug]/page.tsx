import { notFound } from "next/navigation";
import { DocumentationPage } from "@/components/documentation-page";
import { DOCUMENTS, developmentStoryDocument } from "@/lib/documentation-registry.mjs";

const routedDocuments = [...DOCUMENTS, developmentStoryDocument("ko"), developmentStoryDocument("en")];

export const dynamicParams = false;

/** Existing root and CLI pages retain their URLs; the registry supplies every other route. */
export function generateStaticParams() {
  return routedDocuments.filter((document) => document.slug && document.id !== "cli").map(({ locale, slug }) => ({ locale, slug }));
}

type Parameters = { params: Promise<{ locale: string; slug: string }> };

export async function generateMetadata({ params }: Parameters) {
  const { locale, slug } = await params;
  const document = routedDocuments.find((item) => item.locale === locale && item.slug === slug);
  if (!document) notFound();
  return { title: `${document.title} | DocReview RAG`, description: document.summary };
}

export default async function Page({ params }: Parameters) {
  const { locale, slug } = await params;
  const document = routedDocuments.find((item) => item.locale === locale && item.slug === slug);
  if (!document) notFound();
  return <DocumentationPage documentId={document.id} locale={document.locale} />;
}
