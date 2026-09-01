"use client";

import {
  Activity,
  BookOpen,
  Database,
  HelpCircle,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Send,
  SquarePen,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CorpusLab } from "@/components/corpus-lab";
import { Onboarding } from "@/components/onboarding";
import {
  ApiError,
  previewRetrieval,
  previewReview,
  retrieveEvidence,
  reviewQuestion,
} from "@/lib/api";
import { loadConversations, newConversation, ONBOARDING_KEY, saveConversations } from "@/lib/storage";
import type { ChatMessage, Conversation, EvidenceHit, RetrievalProfile } from "@/lib/types";
import { DEFAULT_PROFILE } from "@/lib/types";

type View = "review" | "lab" | "status";

export function ServiceShell() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [view, setView] = useState<View>("review");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [tourOpen, setTourOpen] = useState(false);
  const [profile, setProfile] = useState<RetrievalProfile>(DEFAULT_PROFILE);
  const adminLive = process.env.NEXT_PUBLIC_ADMIN_MODE === "live";

  useEffect(() => {
    const restored = loadConversations();
    const initial = restored.length ? restored : [newConversation()];
    setConversations(initial);
    setActiveId(initial[0].id);
    setTourOpen(window.localStorage.getItem(ONBOARDING_KEY) !== "done");
    if (window.innerWidth <= 560) setSidebarOpen(false);
  }, []);

  const active = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? conversations[0],
    [activeId, conversations],
  );

  function persist(next: Conversation[]) {
    setConversations(saveConversations(next));
  }

  function createReview() {
    const conversation = newConversation();
    persist([conversation, ...conversations]);
    setActiveId(conversation.id);
    setProfile(DEFAULT_PROFILE);
    setView("review");
  }

  function removeReview(id: string) {
    const remaining = conversations.filter((conversation) => conversation.id !== id);
    const next = remaining.length ? remaining : [newConversation()];
    persist(next);
    if (activeId === id) setActiveId(next[0].id);
  }

  function clearReviews() {
    const conversation = newConversation();
    persist([conversation]);
    setActiveId(conversation.id);
  }

  function updateActive(messages: ChatMessage[], selectedProfile = active?.profile ?? null) {
    if (!active) return;
    const firstQuestion = messages.find((message) => message.role === "user")?.text ?? "New review";
    const next = conversations.map((conversation) =>
      conversation.id === active.id
        ? {
            ...conversation,
            title: firstQuestion.slice(0, 52),
            updatedAt: new Date().toISOString(),
            messages,
            profile: selectedProfile,
          }
        : conversation,
    );
    persist(next);
  }

  async function submit() {
    const question = query.trim();
    if (!question || busy || !active) return;
    setQuery("");
    setBusy(true);
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question };
    const pending = [...active.messages, userMessage];
    updateActive(pending);
    try {
      let evidence: EvidenceHit[];
      let response;
      if (adminLive && active.profile) {
        const preview = await previewRetrieval(question, active.profile);
        evidence = preview.results;
        response = await previewReview(question, active.profile);
      } else {
        evidence = await retrieveEvidence(question, active.profile?.k ?? 5);
        response = await reviewQuestion(question, active.profile?.k ?? 5);
      }
      const answer = extractAnswer(response) ?? "Retrieved evidence candidates are shown below.";
      const assistant: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: answer,
        evidence,
        trace: extractTrace(response),
      };
      updateActive([...pending, assistant]);
    } catch (reason) {
      let evidence: EvidenceHit[] = [];
      try {
        evidence = await retrieveEvidence(question, active.profile?.k ?? 5);
      } catch {
        // The original typed failure is the useful message when retrieval also fails.
      }
      const message =
        reason instanceof ApiError && reason.code === "daily_cost_limit"
          ? "The daily answer budget is exhausted. Retrieved evidence is shown without an LLM answer."
          : reason instanceof Error
            ? reason.message
            : "The review could not be completed.";
      updateActive([
        ...pending,
        { id: crypto.randomUUID(), role: "assistant", text: message, evidence },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function applyProfile(nextProfile: RetrievalProfile) {
    setProfile(nextProfile);
    if (active) updateActive(active.messages, nextProfile);
    setView("review");
  }

  function closeTour() {
    window.localStorage.setItem(ONBOARDING_KEY, "done");
    setTourOpen(false);
  }

  return (
    <main className={`service-shell ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <aside className="sidebar">
        <div className="brand"><span>D</span><strong>DocReview</strong></div>
        <button className="new-review" type="button" onClick={createReview}><SquarePen size={17} /><span>New review</span></button>
        <p className="sidebar-label">Recent reviews</p>
        <div className="conversation-list">
          {conversations.map((conversation) => (
            <div className="conversation-row" key={conversation.id}>
              <button type="button" aria-pressed={conversation.id === activeId && view === "review"} onClick={() => { setActiveId(conversation.id); setProfile(conversation.profile ?? DEFAULT_PROFILE); setView("review"); }}>
                <MessageSquare size={15} /><span>{conversation.title}</span>
              </button>
              <button className="delete-review" type="button" aria-label={`Delete ${conversation.title}`} onClick={() => removeReview(conversation.id)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
        <div className="sidebar-nav">
          <button type="button" aria-pressed={view === "lab"} onClick={() => setView("lab")}><Database size={17} /><span>Corpus Lab</span></button>
          <a href="/docreview-rag-agent/docs/" target="_blank" rel="noreferrer"><BookOpen size={17} /><span>Documentation</span></a>
          <button type="button" aria-pressed={view === "status"} onClick={() => setView("status")}><Activity size={17} /><span>System status</span></button>
          <button type="button" onClick={() => setTourOpen(true)}><HelpCircle size={17} /><span>Show tutorial</span></button>
          <button type="button" onClick={clearReviews}><Trash2 size={17} /><span>Clear conversations</span></button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <button className="icon-button" type="button" aria-label="Toggle sidebar" onClick={() => setSidebarOpen((value) => !value)}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>
          <div><strong>{view === "review" ? active?.title ?? "New review" : view === "lab" ? "Corpus Lab" : "System status"}</strong><span>Evidence-first SEC and DART filing review</span></div>
          <span className="health"><i />Runtime</span>
        </header>

        {view === "review" && <section className="review-workspace">
          <div className="messages">
            {!active?.messages.length && <div className="welcome"><p className="eyebrow">Grounded by design</p><h1>Review filings with verifiable evidence.</h1><p>Ask across SEC 10-K and DART reports. Unsupported answers terminate as NOT_IN_DOCS.</p><div className="suggestions"><button type="button" onClick={() => setQuery("What drove NVIDIA data center revenue growth?")}>NVIDIA growth drivers</button><button type="button" onClick={() => setQuery("삼성전자 메모리 사업의 주요 위험은 무엇인가요?")}>삼성전자 메모리 위험</button></div></div>}
            {active?.messages.map((message) => <article className={`message ${message.role}`} key={message.id}><div className="message-role">{message.role === "user" ? "You" : "DocReview"}</div><div className="message-body"><p>{message.text}</p>{message.evidence?.length ? <details className="evidence"><summary>{message.evidence.length} cited evidence result{message.evidence.length === 1 ? "" : "s"}</summary>{message.evidence.map((hit) => <div className="evidence-hit" key={hit.chunk_id}><strong>{hit.citation}</strong><span>{hit.doc_id} · chars {hit.start_char}–{hit.end_char}</span><p>{hit.body}</p></div>)}</details> : null}{message.trace && <pre className="trace">{message.trace}</pre>}</div></article>)}
            {busy && <div className="thinking">Retrieving and checking evidence…</div>}
          </div>
          <div className="composer-wrap">{active?.profile && <div className="profile-chip">Session profile · {active.profile.strategy} · {active.profile.lexical_ranker ?? "vector"} · k={active.profile.k}</div>}<label className="composer"><textarea value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder="Ask a question about the filing corpus" rows={1} /><button type="button" aria-label="Send question" disabled={busy || !query.trim()} onClick={() => void submit()}><Send size={17} /></button></label><p>Answers must cite retrieved filing evidence. Provider calls are rate- and cost-limited.</p></div>
        </section>}

        {view === "lab" && <CorpusLab live={adminLive} profile={profile} onProfileChange={setProfile} onApplyProfile={applyProfile} />}
        {view === "status" && <section className="status-page"><p className="eyebrow">System status</p><h1>Runtime readiness</h1><div className="metric-grid"><div className="metric"><span>Database</span><strong>Connected</strong></div><div className="metric"><span>Retrieval</span><strong>Ready</strong></div><div className="metric"><span>Administrator</span><strong>{adminLive ? "SSH operator" : "Read only"}</strong></div></div></section>}
      </section>
      {tourOpen && <Onboarding onClose={closeTour} />}
    </main>
  );
}

function extractAnswer(payload: Record<string, unknown>): string | null {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = root.report as Record<string, unknown> | null;
  return report && typeof report.answer === "string" ? report.answer : null;
}

function extractTrace(payload: Record<string, unknown>): string {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const values = ["status", "total_requests", "total_input_tokens", "total_output_tokens", "total_time_seconds"];
  return values.filter((key) => root[key] !== undefined).map((key) => `${key}=${String(root[key])}`).join(" · ");
}
