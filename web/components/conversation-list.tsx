"use client";
import { MessageSquare, Trash2 } from "lucide-react";

import { useI18n } from "@/lib/i18n";
import type { Conversation } from "@/lib/types";

interface ConversationListProps {
  conversations: Conversation[];
  activeConversationId: string;
  /** A row reads as selected only while the Review workspace is the one on screen. */
  reviewVisible: boolean;
  titles: Record<string, string>;
  onOpen: (conversationId: string) => void;
  onDelete: (conversationId: string) => void;
}

/** Sidebar list of saved conversations; an empty draft stays behind "New chat" instead of getting a row. */
export function ConversationList({ conversations, activeConversationId, reviewVisible, titles, onOpen, onDelete }: ConversationListProps) {
  const { t } = useI18n();
  return (
    <>
      <p className="sidebar-label">{t("Recent reviews")}</p>
      <div className="conversation-list" data-tour="recent-reviews">
        {conversations.filter(conversation => conversation.messages.length > 0).map((conversation) => (
          <div className="conversation-row" key={conversation.id}>
            <button type="button" aria-pressed={conversation.id === activeConversationId && reviewVisible} onClick={() => onOpen(conversation.id)}>
              <MessageSquare size={15} /><span>{titles[conversation.id]}</span>
            </button>
            {conversation.messages.length > 0 && <button className="delete-review" type="button" aria-label={t("Delete {p0}", { p0: conversation.title })} onClick={() => onDelete(conversation.id)}><Trash2 size={14} /></button>}
          </div>
        ))}
      </div>
    </>
  );
}
