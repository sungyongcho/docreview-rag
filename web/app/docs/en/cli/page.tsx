import { DocumentationPage } from "@/components/documentation-page";
import { documentationDocument } from "@/lib/documentation-registry.mjs";
export const metadata = { title: `${documentationDocument("cli", "en")!.title} | DocReview RAG` };
export default function Page() { return <DocumentationPage documentId="cli" locale="en" />; }
