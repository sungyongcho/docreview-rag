import type { ComponentPropsWithoutRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

function SafeLink({ href, children, ...props }: ComponentPropsWithoutRef<"a">) {
  const safe = href?.startsWith("https://") || href?.startsWith("http://") || href?.startsWith("mailto:");
  if (!safe) return <span>{children}</span>;
  return <a {...props} href={href} target="_blank" rel="noreferrer noopener">{children}</a>;
}

function OmittedImage({ alt }: { alt?: string }) {
  return <span className="markdown-image-omitted">[Image omitted{alt ? `: ${alt}` : ""}]</span>;
}

function ResponsiveTable({ children, ...props }: ComponentPropsWithoutRef<"table">) {
  return <div className="markdown-table-wrap"><table {...props}>{children}</table></div>;
}

export function MarkdownMessage({ children }: { children: string }) {
  return (
    <div className="markdown-body">
      <Markdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        components={{
          a: SafeLink,
          img: OmittedImage,
          table: ResponsiveTable,
        }}
      >
        {children}
      </Markdown>
    </div>
  );
}
