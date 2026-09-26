"use client";
import { Activity, FlaskConical, Hammer, Settings, SquarePen, TriangleAlert, X } from "lucide-react";

import { ConversationList } from "@/components/conversation-list";
import { CreatorSignature } from "@/components/creator-signature";
import { DevModeBubble } from "@/components/dev-mode-bubble";
import { GuidesNavigation } from "@/components/guides-navigation";
import { BuildInfo, ProductBrand } from "@/components/product-brand";
import { SOURCE_REPOSITORY_URL } from "@/lib/dev-mode";
import { useI18n } from "@/lib/i18n";
import type { NavigationTarget } from "@/lib/navigation";
import type { Conversation } from "@/lib/types";
import type { RuntimeHealthKind } from "@/lib/use-runtime-health";

interface ServiceSidebarProps {
  open: boolean;
  onClose: () => void;
  view: NavigationTarget["view"];
  /** The active conversation is still empty, so "New chat" is the screen being shown. */
  newChatActive: boolean;
  onNewChat: () => void;
  conversations: Conversation[];
  activeConversationId: string;
  conversationTitles: Record<string, string>;
  onDeleteConversation: (conversationId: string) => void;
  environment: "dev" | "prod" | undefined;
  modeLabel: string | null;
  buildNeedsAttention: boolean;
  healthKind: RuntimeHealthKind;
  showLocalModel: boolean;
  localModel: string | null;
  localModelUnavailable: boolean;
  onNavigate: (target: NavigationTarget) => void;
  onOpenSettings: () => void;
  onOpenAbout: () => void;
}

/** Navigation drawer: new chat, saved conversations, workspace links and the server mode. */
export function ServiceSidebar({
  open, onClose, view, newChatActive, onNewChat, conversations, activeConversationId, conversationTitles, onDeleteConversation,
  environment, modeLabel, buildNeedsAttention, healthKind, showLocalModel, localModel, localModelUnavailable, onNavigate, onOpenSettings, onOpenAbout,
}: ServiceSidebarProps) {
  const { t } = useI18n();
  return (
    <>
      {open && <button className="sidebar-backdrop" type="button" aria-label={t("Close navigation overlay")} onClick={onClose} />}
      <aside id="service-navigation" className="sidebar" inert={!open} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }}>
        <div className="brand"><ProductBrand onActivate={onNewChat} actionLabel={`DocReview RAG · ${t("New chat")}`} /><button className="icon-button sidebar-close" type="button" aria-label={t("Close sidebar")} onClick={onClose}><X size={18} /></button></div>
        <button className="new-review" data-tour="new-review" type="button" aria-pressed={newChatActive} onClick={onNewChat}><SquarePen size={17} /><span>{t("New chat")}</span></button>
        <ConversationList
          conversations={conversations}
          activeConversationId={activeConversationId}
          reviewVisible={view === "review"}
          titles={conversationTitles}
          onOpen={(conversationId) => onNavigate({ view: "review", conversationId })}
          onDelete={onDeleteConversation}
        />
        <BuildInfo onOpen={onOpenAbout} mode={environment && <RuntimeModeBadge environment={environment} modeLabel={modeLabel} />} />
        <div className="sidebar-nav">
          <GuidesNavigation />
          <button data-tour="build" type="button" aria-pressed={view === "build"} onClick={() => onNavigate({ view: "build" })}><Hammer size={17} /><span>{t("Build")}</span>{buildNeedsAttention && <><i className="nav-dot" aria-hidden="true" /><span className="sr-only">{t(", needs attention")}</span></>}</button>
          <button data-tour="measure" type="button" aria-pressed={view === "measure"} onClick={() => onNavigate({ view: "measure" })}><FlaskConical size={17} /><span>{t("Measure")}</span></button>
          <button data-tour="system" className={`nav-secondary system-status-button ${healthBadge(healthKind)}`} type="button" aria-label={t("System · {p0}", { p0: t(healthLabel(healthKind)) })} aria-pressed={view === "system"} onClick={() => onNavigate({ view: "system", tab: "status" })}><Activity size={17} /><span>{t("System")}</span><span className="system-health"><i aria-hidden="true" />{t(healthLabel(healthKind))}</span></button>
          <button data-tour="settings" type="button" onClick={onOpenSettings}><Settings size={17} /><span>{t("Settings")}</span></button>
        </div>
        {showLocalModel && <LocalModelBadge model={localModel} unavailable={localModelUnavailable} />}
        <CreatorSignature />
      </aside>
    </>
  );
}

/** PROD links to the source repository through the DEV promotion bubble; DEV only names the environment. */
function RuntimeModeBadge({ environment, modeLabel }: { environment: "dev" | "prod"; modeLabel: string | null }) {
  const { t } = useI18n();
  if (environment === "prod") {
    return (
      <DevModeBubble>
        <a className="runtime-mode-badge prod" href={SOURCE_REPOSITORY_URL} target="_blank" rel="noreferrer" aria-label={modeLabel ?? undefined}>
          <strong>PROD</strong><span>{t("MODE")}</span>
        </a>
      </DevModeBubble>
    );
  }
  return (
    <div className={`runtime-mode-badge ${environment}`} role="note" aria-label={modeLabel ?? undefined} title={t("Server environment: {p0}", { p0: modeLabel ?? "" })}>
      <strong>{environment.toUpperCase()}</strong><span>{t("MODE")}</span>
    </div>
  );
}

/** Answers leave the hosted provider while a local engine is selected, so the sidebar keeps saying so. */
function LocalModelBadge({ model, unavailable }: { model: string | null; unavailable: boolean }) {
  const { t } = useI18n();
  return (
    <div className="local-mode-badge" role="note">
      <TriangleAlert size={14} aria-hidden="true" />
      <span className="local-mode-label">{t("LOCAL MODEL")}{model ? t(" · {p0}", { p0: model }) : ""}{unavailable ? t(" · Unavailable") : ""}</span>
      <span className="local-mode-note">{t("Answers use the selected model server. Choose an engine and model above the conversation input. API health and model availability are checked separately.")}{" "}</span>
    </div>
  );
}

function healthBadge(kind: RuntimeHealthKind): string {
  if (kind === "healthy") return "ready";
  if (kind === "checking") return "unknown";
  return "degraded";
}

function healthLabel(kind: RuntimeHealthKind): string {
  return kind === "api_down" ? "API down" : kind.replace("_", " ");
}
