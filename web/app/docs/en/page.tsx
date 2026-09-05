import { DocumentationPage } from "@/components/documentation-page";
import { documentationDocument } from "@/lib/documentation-registry.mjs";
export const metadata = { title: `${documentationDocument("overview", "en")!.title} | DocReview RAG` };
export default function Page() { return <DocumentationPage documentId="overview" locale="en" />; }
