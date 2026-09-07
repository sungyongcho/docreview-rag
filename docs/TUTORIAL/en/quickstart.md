# Quick Start

Use this guide to try an already running DocReview RAG instance. Start with a small question, read its evidence, and explore the published filings and measured results. The available corpus and request limits belong to that instance.

## 1. Find your way around {#qs-app-1}

**New review** opens a conversation. **Build → Documents** shows the available filings. **Measure** provides the published snapshots and their recorded results. **System → System status** explains service availability.

If the public document list is empty, clear any filters and check the displayed availability message. An empty public catalog does not establish that the service has no private data. You can still explore available saved results without submitting a question.

### SCREENSHOT NEEDED
<!-- Feature: visitor Quick Start orientation; locale=en; light mode; running public instance with conversation, Build → Documents and Measure navigation visible. Show actual available or empty data without operator actions. Preserve existing assets. -->

## 2. Ask your first question {#qs-app-2}

Open **New review** and choose a company and fiscal year that are present in the available catalog. Keep the instance's configured answer policy. **Inspect request** shows the scope and filters that the next question will use; opening it does not send anything.

If NVIDIA FY2024 is available, try:

```text
What drove NVIDIA's data center revenue growth in FY2024? Cite evidence from the filing.
```

Otherwise ask a similarly focused question about an available filing. Select **Send question** once. Read the execution summary below your question while it runs; **Stop request** stops an active request. If a request is unavailable or limited, read the displayed reason and inspect an existing result instead.

### SCREENSHOT NEEDED
<!-- Feature: visitor first question; locale=en; light mode; running public instance with a catalog-supported question and its actual execution summary or stated request limitation. Keep credentials hidden; do not manufacture an answer. Preserve existing assets. -->

## 3. Read the answer and its evidence {#qs-app-3}

A `SUPPORTED` answer still needs source verification. Open its citations and **Retrieved evidence candidates**. Check the company, fiscal year, filing section, and quoted passage against each claim. A candidate is not automatically a citation used in the answer.

`NOT_IN_DOCS` means the available evidence did not support the requested answer. An operational failure is a separate outcome; read the reason instead of interpreting it as a finding about the filing. [Answers](answers.md#inspection) explains the inspection controls, and [Retrieval](retrieval.md#step-8) explains the evidence path.

### SCREENSHOT NEEDED
<!-- Feature: visitor answer verification; locale=en; light mode; a real saved or completed answer with an expanded citation and evidence candidate showing source company, fiscal year and passage. Preserve existing assets. -->

## 4. Browse the source documents {#qs-app-4}

Open **Build → Documents**, search for the company or document identifier, and select a row. Read the filing identity, fiscal year, source link when available, and chunk previews. Use **Reset filters** if a filtered list hides the filing you expected.

The public catalog contains only documents eligible through published snapshots. Reading a document does not change its data. [Documents](documents.md#visibility) explains the visibility boundary and available filters.

### SCREENSHOT NEEDED
<!-- Feature: visitor source document inspection; locale=en; light mode; public document list and selected filing details with company, FY, original source and chunk evidence. Preserve existing assets. -->

## 5. Inspect published snapshots {#qs-app-5}

In **Measure**, open the available saved snapshots and inspect a snapshot's document count, dataset, settings, and recorded metrics. When two snapshots can be compared, read the compatibility warning and shared cases before interpreting score differences. With one or no snapshots, keep the unavailable comparison explicit.

Browsing and comparing stored snapshots does not run a new evaluation. [Snapshots](snapshots.md#comparison) explains what makes results comparable. Continue to [Answers](answers.md) for the full usage guide, or return to [Overview](overview.md#start) to choose another path.

### SCREENSHOT NEEDED
<!-- Feature: visitor published snapshot inspection; locale=en; light mode; actual published snapshot details and an available or explicitly unavailable comparison with compatibility facts. Preserve existing assets. -->
