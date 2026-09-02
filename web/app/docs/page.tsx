import Link from "next/link";

export default function DocumentationPage() {
  return (
    <main className="docs-shell">
      <p className="eyebrow">DocReview documentation</p>
      <h1>Review filings without losing the evidence boundary.</h1>
      <p>DocReview separates casual conversation from filing review, resolves issuer and corpus scope, routes mixed-language queries per corpus, and validates every cited answer.</p>
      <div className="docs-grid">
        <section><span>Build</span><h2>Seven ordered stages from filings to evaluation, each with real state and one action</h2></section>
        <section><span>Review</span><h2>Conversation gate → scope → translated retrieval → citation check</h2></section>
        <section><span>Evidence</span><h2>Inspect, pin, exclude, and revalidate signed candidate snapshots</h2></section>
        <section><span>Engines</span><h2>OpenAI API or server-side OpenAI-compatible/Ollama Local LLM</h2></section>
        <section><span>Evaluation</span><h2>Compare metrics, inspect cases, and apply a measured retrieval set</h2></section>
        <section><span>Playground</span><h2>Preview retrieval and review through an explicit profile before trusting a preset</h2></section>
        <section><span>Embeddings</span><h2>text-embedding-3-large at 384 dimensions with persisted vector identity</h2></section>
        <section><span>Failures</span><h2>Provider and infrastructure errors never masquerade as NOT_IN_DOCS</h2></section>
      </div>
      <Link href="/">Return to service</Link>
    </main>
  );
}
