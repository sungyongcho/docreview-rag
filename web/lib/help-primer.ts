import { HELP_TOPICS, type HelpTopic } from "./help-content";

export interface HelpPrimer { summary: string; steps: readonly string[]; documentId?: string }
export interface HelpCluster { id: string; title: string; summary: string; topicIds: readonly string[] }
export interface HelpGroup { id: string; title: string; summary: string; clusters: readonly HelpCluster[] }

const PRIMERS: Record<string, HelpPrimer> = {
  "review.scope": {
    "summary": "Choose which filing collection can answer this question.",
    "steps": [
      "Choose Auto, SEC, or DART.",
      "Check the company and fiscal-year filters.",
      "Read the server-confirmed scope after execution."
    ]
  },
  "review.preset": {
    "summary": "Start with a search preset; customize only the settings you need.",
    "steps": [
      "Choose Balanced, Korean, or Accuracy.",
      "Use the question mark to compare their purpose.",
      "Choose Custom to open the editor."
    ]
  },
  "review.filters": {
    "summary": "Narrow the available evidence without changing the question.",
    "steps": [
      "Open Review settings → Filters.",
      "Choose available companies, years, and report types.",
      "Correct unfinished entries before sending."
    ]
  },
  "review.composer": {
    "summary": "Ask one clear question and name the company or year when it matters.",
    "steps": [
      "Describe what you want to verify.",
      "Check scope, engine, and filters.",
      "Send when the question and settings are ready."
    ]
  },
  "review.send": {
    "summary": "Send starts a real review using the settings shown above the question.",
    "steps": [
      "Confirm the selected engine is available.",
      "Send once and follow actual execution status.",
      "Read the answer together with its citations."
    ]
  },
  "review.evidence": {
    "summary": "Pin or exclude passages for a new review; the current answer stays intact.",
    "steps": [
      "Open the retrieved evidence candidates.",
      "Pin useful passages or exclude unsuitable ones.",
      "Review again with the selected evidence."
    ]
  },
  "review.run-trace": {
    "summary": "Use the recorded run to understand what happened and why it stopped.",
    "steps": [
      "Open the result’s run trace.",
      "Check the failure category and measured usage.",
      "Open the matching setting or diagnostic guide."
    ]
  },
  "review.readiness": {
    "summary": "Check whether the corpus can support retrieval before running a question.",
    "steps": [
      "Read what the corpus total describes.",
      "Open View corpus readiness.",
      "Return with Back to conversation."
    ]
  },
  "review.evidence-policy": {
    "summary": "Control how much history and evidence the model receives.",
    "steps": [
      "Open Review settings → Evidence.",
      "Adjust only the context limit you need.",
      "Inspect the next request before sending."
    ]
  },
  "review.run-limits": {
    "summary": "Set limits for the complete run, including repeated calls and retries.",
    "steps": [
      "Open Review settings → Run limits.",
      "Distinguish seconds, iterations, and tokens.",
      "Compare a failure with its recorded limit."
    ]
  },
  "field:strategy": {
    "summary": "Choose keyword, semantic, or combined retrieval.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:lexical_ranker": {
    "summary": "Choose how the keyword search lane ranks matching passages.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:k": {
    "summary": "Set how many final passages retrieval returns.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:candidate_k": {
    "summary": "Set the candidate pool before the final evidence is selected.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:rrf_k": {
    "summary": "Adjust how much the combined rank rewards agreement between search lanes.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:bm25_k1": {
    "summary": "Adjust how quickly repeated keyword matches stop adding value.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:bm25_b": {
    "summary": "Adjust how keyword ranking accounts for passage length.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:bm25_idf": {
    "summary": "Choose how BM25 weighs rare and common terms.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:reranker": {
    "summary": "Reorder retrieved candidates by relevance before choosing the final set.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "field:route_by_language": {
    "summary": "Use the configured language route when retrieving evidence.",
    "steps": [
      "Inspect the current value and its purpose.",
      "Change one setting at a time.",
      "Compare retrieval evidence before adopting it."
    ]
  },
  "build.stage.filings": {
    "summary": "Download missing original reports; parsing happens afterward.",
    "steps": [
      "Choose the source, companies, and fiscal years.",
      "Check the acquisition prerequisites.",
      "Download only when the source is missing."
    ]
  },
  "build.stage.index": {
    "summary": "Turn downloaded reports into documents and citable chunks.",
    "steps": [
      "Check the intended manifest and source count.",
      "Ingest the selected manifest.",
      "Verify the document and chunk counts."
    ]
  },
  "build.stage.embeddings": {
    "summary": "Prepare semantic vectors only when their current identity is missing or mismatched.",
    "steps": [
      "Check the provider and pending count.",
      "Review the database-wide scope and cost.",
      "Backfill only what is required."
    ]
  },
  "build.stage.lexical": {
    "summary": "Make keyword statistics match the current chunks.",
    "steps": [
      "Check BM25 readiness.",
      "Rebuild only if statistics are missing.",
      "Continue to retrieval or evaluation."
    ]
  },
  "system.local-policy": {
    "summary": "Check the local server and distinguish answer models from embedding models.",
    "steps": [
      "Open Settings → Local LLM for the connection.",
      "Use Default and run connection diagnostics.",
      "Choose an available answer model in the conversation."
    ]
  },
  "system.status": {
    "summary": "Read API, database, corpus, and model availability as separate checks.",
    "steps": [
      "Refresh the current status.",
      "Read the specific missing prerequisite.",
      "Open the relevant workflow or diagnostic guide."
    ]
  },
  "build.jobs.center": {
    "summary": "Select an actual job to inspect progress, results, or failure.",
    "steps": [
      "Find the job by target and state.",
      "Open its details and recorded result.",
      "Cancel or retry only when the action is offered."
    ]
  },
  "build.documents.filters": {
    "summary": "Find the intended filing with real company and year choices.",
    "steps": [
      "Search by company code or name.",
      "Choose a fiscal year and optional filters.",
      "Remove a chip to broaden the results."
    ]
  },
  "build.documents.list": {
    "summary": "Open a filing when you need its source and preparation details.",
    "steps": [
      "Select the document row or name.",
      "Inspect its identity, chunks, and index state.",
      "Return to the preserved list when finished."
    ]
  }
};

const GROUP_DEFINITIONS = [
  {
    "id": "answers",
    "title": "Questions and evidence",
    "summary": "Prepare a question, then inspect its answer.",
    "clusters": [
      {
        "id": "question",
        "title": "Prepare a question",
        "summary": "Scope, presets, filters, and sending."
      },
      {
        "id": "evidence",
        "title": "Read the answer",
        "summary": "Citations, selected evidence, and execution."
      },
      {
        "id": "review-settings",
        "title": "Review limits",
        "summary": "Context, custom retrieval, and run limits."
      }
    ]
  },
  {
    "id": "corpus",
    "title": "Prepare documents",
    "summary": "Acquire, index, and manage your filings.",
    "clusters": [
      {
        "id": "pipeline",
        "title": "Acquire and index",
        "summary": "Sources, chunks, embeddings, and BM25."
      },
      {
        "id": "documents",
        "title": "Browse documents",
        "summary": "Find a filing and inspect its source."
      },
      {
        "id": "jobs",
        "title": "Track jobs",
        "summary": "Progress, results, and supported recovery."
      }
    ]
  },
  {
    "id": "quality",
    "title": "Search and evaluate",
    "summary": "Test evidence and compare measured results.",
    "clusters": [
      {
        "id": "playground",
        "title": "Try retrieval",
        "summary": "Questions, rankings, and retrieved evidence."
      },
      {
        "id": "golden",
        "title": "Prepare a dataset",
        "summary": "Canonical questions and editable drafts."
      },
      {
        "id": "runs",
        "title": "Run evaluations",
        "summary": "Experiment setup and actual results."
      },
      {
        "id": "snapshots",
        "title": "Compare and reuse",
        "summary": "Results, compatibility, and snapshots."
      }
    ]
  },
  {
    "id": "settings",
    "title": "Settings and diagnosis",
    "summary": "Tune search or check the runtime.",
    "clusters": [
      {
        "id": "retrieval",
        "title": "Search settings",
        "summary": "Search method, evidence size, and ranking."
      },
      {
        "id": "connection",
        "title": "Local models",
        "summary": "Default server, model roles, and diagnostics."
      },
      {
        "id": "status",
        "title": "Runtime checks",
        "summary": "Service health, API facts, and usage."
      },
      {
        "id": "defaults",
        "title": "Saved defaults",
        "summary": "Starting values for future work."
      }
    ]
  }
];

const PROFILE_FIELDS = new Set(["strategy", "lexical_ranker", "k", "candidate_k", "rrf_k", "bm25_k1", "bm25_b", "bm25_idf", "reranker", "route_by_language"]);

/** Keep existing control IDs while presenting a small task-oriented navigation tree. */
function clusterFor(topic: HelpTopic): string {
  if (PROFILE_FIELDS.has(topic.id.split(".").at(-1)!)) return "retrieval";
  if (topic.id.startsWith("review.")) {
    if (["review.evidence", "review.run-trace"].includes(topic.id)) return "evidence";
    if (["review.rag", "review.retrieval", "review.evidence-policy", "review.run-limits"].includes(topic.id)) return "review-settings";
    return "question";
  }
  if (topic.id.startsWith("build.documents.")) return "documents";
  if (topic.id.startsWith("build.jobs.")) return "jobs";
  if (topic.id.startsWith("build.")) return "pipeline";
  if (topic.id.startsWith("measure.playground.")) return "playground";
  if (topic.id.startsWith("measure.golden.")) return "golden";
  if (topic.id.startsWith("measure.runs.")) return "runs";
  if (topic.id.startsWith("measure.compare.") || topic.id.startsWith("measure.snapshots.")) return "snapshots";
  if (topic.id.startsWith("measure.defaults.") || topic.id.startsWith("measure.presets.")) return "defaults";
  return topic.id === "system.local-policy" ? "connection" : "status";
}

const topics = Object.values(HELP_TOPICS).flat();
export const HELP_GROUPS: readonly HelpGroup[] = GROUP_DEFINITIONS.map((group) => ({ ...group, clusters: group.clusters.map((cluster) => ({ ...cluster, topicIds: topics.filter((topic) => clusterFor(topic) === cluster.id).map((topic) => topic.id) })) }));

/** Lead with one clear meaning and three small actions; full definitions remain available. */
export function getHelpPrimer(topic: HelpTopic): HelpPrimer {
  const primer = topic.guide ?? PRIMERS[topic.id] ?? PRIMERS[`field:${topic.id.split(".").at(-1)}`] ?? {
    summary: topic.body[0],
    steps: ["Open the related control.", "Check its current value or recorded result.", "Use its explicit action only when ready."],
  };
  const documents: Record<string, string> = { question: "answers", evidence: "answers", "review-settings": "settings", pipeline: "indexing", documents: "documents", jobs: "runtime", playground: "retrieval", golden: "evaluation", runs: "evaluation", snapshots: "snapshots", retrieval: "settings", connection: "ollama", status: "runtime", defaults: "settings" };
  return { ...primer, documentId: documents[clusterFor(topic)] };
}
