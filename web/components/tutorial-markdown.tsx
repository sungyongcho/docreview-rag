import type { ReactNode } from "react";

export function TutorialMarkdown({ content }: { content: ReactNode }) {
  return <article className="markdown-body tutorial-body">{content}</article>;
}
