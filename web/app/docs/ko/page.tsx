import { DocumentationPage } from "@/components/documentation-page";
import { documentationDocument } from "@/lib/documentation-registry.mjs";
export const metadata = { title: `${documentationDocument("overview", "ko")!.title} | DocReview RAG` };
export default function Page() { return <DocumentationPage documentId="overview" locale="ko" />; }
