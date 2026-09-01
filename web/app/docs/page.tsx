import Link from "next/link";

export default function DocumentationPage() {
  return (
    <main className="docs-shell">
      <p className="eyebrow">DocReview documentation</p>
      <h1>Documentation is being prepared.</h1>
      <p>
        Architecture, implementation chapters, evaluation evidence, and operations will live here.
      </p>
      <div className="docs-grid">
        <section><span>Start here</span><h2>How DocReview works</h2></section>
        <section><span>Build</span><h2>Engineering chapters</h2></section>
        <section><span>Reference</span><h2>API and operations</h2></section>
      </div>
      <Link href="/">Return to service</Link>
    </main>
  );
}
