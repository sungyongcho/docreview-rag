import { createElement } from "react";
import Markdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { DOCUMENTATION_REGISTRY, documentationDocuments, documentationLink } from "./documentation-registry.mjs";
export { DOCUMENTS } from "./documentation-registry.mjs";

function nodeText(node) {
  return node.value ?? (node.children ?? []).map(nodeText).join("");
}

export function renderTutorial(source, { locale = "ko", renderCode, renderDevelopmentNotice, renderImage, assetVersion, math = false, registry = DOCUMENTATION_REGISTRY } = {}) {
  const steps = documentationDocuments(registry)
    .filter((document) => document.locale === locale)
    .flatMap((document) => document.steps.map((step) => ({ ...step, source: document.source })))
    .sort((a, b) => a.number - b.number);
  const codes = [];
  const headings = [], images = [], links = [];
  const used = new Set();
  function prepare() {
    return (tree) => {
      const definitions = new Map(tree.children.filter((n) => n.type === "definition").map((n) => [n.identifier.toLowerCase(), n]));
      function visit(node) {
        for (const [index, child] of (node.children ?? []).entries()) {
          const picture = child.type === "paragraph" && child.children.length === 1 ? child.children[0] : null;
          const following = node.children[index + 1];
          if ((picture?.type === "image" || picture?.type === "imageReference") && following?.type === "paragraph" && following.children.length === 1 && following.children[0].type === "emphasis") {
            picture.data = { ...picture.data, hProperties: { ...picture.data?.hProperties, "data-tutorial-caption": nodeText(following) } };
          }
        }
        if (node.children) node.children = node.children.map((child) => child.type === "html" && child.value.trim() === "<!-- tutorial-steps -->" ? {
          type: "list", ordered: true, start: 1, spread: false,
          data: { hProperties: { className: "docs-steps" } },
          children: steps.map((step) => ({ type: "listItem", spread: false, children: [{ type: "paragraph", children: [{ type: "link", url: `${step.source}#${step.anchor}`, children: [{ type: "text", value: step.title }] }] }] })),
        } : child);
        if (node.type === "imageReference" || node.type === "linkReference") {
          const definition = definitions.get(node.identifier.toLowerCase());
          if (!definition) throw new Error(`Missing Markdown reference: ${node.identifier}`);
          node.type = node.type === "imageReference" ? "image" : "link";
          node.url = definition.url;
          node.title = definition.title;
        }
        if (node.type === "blockquote" && node.children[0]?.type === "paragraph") {
          const first = node.children[0].children[0];
          if (first?.type === "text" && /^\[!DEV\](?:\n|$)/.test(first.value)) {
            first.value = first.value.replace(/^\[!DEV\]\n?/, "");
            if (!nodeText(node.children[0]).trim()) node.children.shift();
            node.data = { ...node.data, hProperties: { "data-development-only": "true" } };
          }
          if (first?.type === "text" && /^\[!GOAL\](?:\n|$)/.test(first.value)) {
            first.value = first.value.replace(/^\[!GOAL\]\n?/, "");
            if (!nodeText(node.children[0]).trim()) node.children.shift();
            node.data = { ...node.data, hProperties: { "data-goal": "true" } };
          }
        }
        if (node.type === "heading") {
          const explicit = nodeText(node).match(/\s+\{#([a-z][a-z0-9-]*)\}\s*$/);
          if (explicit) {
            const last = node.children.at(-1);
            if (last?.type !== "text") throw new Error("Explicit heading ID must follow plain text");
            last.value = last.value.replace(/\s+\{#[a-z][a-z0-9-]*\}\s*$/, "");
          }
          const text = nodeText(node);
          const base = explicit?.[1] ?? (text.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").trim().replace(/\s+/g, "-") || "section");
          if (explicit && used.has(base)) throw new Error(`Duplicate explicit tutorial heading: ${base}`);
          let id = base;
          for (let suffix = 2; used.has(id); suffix += 1) id = `${base}-${suffix}`;
          used.add(id);
          node.data = { ...node.data, hProperties: { id } };
          headings.push({ id, text, depth: node.depth });
          if (text === "SCREENSHOT NEEDED") node.data = { ...node.data, hProperties: { ...node.data.hProperties, "data-screenshot-needed": "true" } };
        }
        if (node.type === "code") {
          node.data = { ...node.data, hProperties: { "data-code-index": codes.length } };
          codes.push({ code: node.value, language: node.lang || "text" });
        }
        if (node.type === "image") {
          const path = decodeURIComponent(node.url).replace(/^\.\.\/assets\//, "assets/").replace(/^\.\//, "");
          if (!/^assets\/[\p{L}\p{N}_. /-]+\.(png|jpe?g|webp|gif)$/iu.test(path) || path.split("/").some((part) => !part || part === ".." || part === ".")) {
            throw new Error(`Tutorial image must be inside assets/: ${node.url}`);
          }
          if (!node.alt?.trim()) throw new Error(`Tutorial image requires alt text: ${path}`);
          images.push(path);
          node.url = `/docreview-rag-agent/tutorial-assets/${path.slice(7).split("/").map(encodeURIComponent).join("/")}`;
          if (assetVersion) node.url += `?v=${encodeURIComponent(assetVersion)}`;
        }
        if (node.type === "link") {
          const url = node.url;
          if (!/^(https?:|mailto:)/i.test(url)) {
            const [file, ...fragments] = url.replace(/^\.\//, "").split("#");
            const hash = fragments.length ? decodeURIComponent(fragments.join("#")) : "";
            const target = file ? documentationLink(file, hash, locale, registry) : null;
            if (file && !target) throw new Error(`Unknown tutorial link: ${url}`);
            const anchor = target?.hash ?? hash;
            links.push({ file: target?.document.file ?? null, hash: anchor });
            node.url = `${target?.document.href ?? ""}${anchor ? `#${encodeURIComponent(anchor)}` : ""}`;
          }
        }
        for (const child of node.children ?? []) visit(child);
      }
      visit(tree);
    };
  }
  const content = Markdown({
    skipHtml: true,
    remarkPlugins: [remarkGfm, ...(math ? [remarkMath] : []), prepare],
    rehypePlugins: math ? [rehypeKatex] : [],
    components: {
      a: ({ children, href }) => {
        const external = /^https?:\/\//i.test(href ?? "");
        return createElement("a", { href, ...(external ? { target: "_blank", rel: "noopener noreferrer" } : {}) }, children,
          external ? createElement("span", { className: "visually-hidden" }, locale === "ko" ? " · 새 탭에서 열림" : " · Opens in a new tab") : null);
      },
      blockquote: ({ children, node }) => node.properties["data-goal"] === "true"
        ? createElement("aside", { className: "docs-goal" },
          createElement("span", { className: "docs-goal-label" }, locale === "ko" ? "목표" : "Goal"), children)
        : node.properties["data-development-only"] === "true"
          ? (renderDevelopmentNotice?.(children) ?? createElement("aside", { className: "docs-development-notice" }, createElement("strong", null, locale === "ko" ? "개발 모드 전용" : "DEV only"), children))
          : createElement("blockquote", null, children),
      ...(renderCode ? { pre: ({ children }) => children?.props?.["data-code-index"] === undefined ? createElement("pre", null, children) : renderCode(codes[Number(children.props["data-code-index"])]) } : {}),
      ...Object.fromEntries([1, 2, 3, 4, 5, 6].map((depth) => [`h${depth}`, ({ children, id, node }) => node?.properties?.["data-screenshot-needed"] === "true" ? null : createElement(`h${depth}`, { id }, createElement("a", { href: `#${encodeURIComponent(id)}`, className: "docs-heading-link" }, children, createElement("span", { "aria-hidden": true, className: "docs-heading-hash" }, " #")))])),
      table: ({ children }) => createElement("div", { className: "markdown-table-wrap", tabIndex: 0, role: "region", "aria-label": locale === "ko" ? "가로로 스크롤할 수 있는 표" : "Scrollable table" }, createElement("table", null, children)),
      img: ({ src, alt, title, node }) => renderImage
        ? renderImage({ src, alt, title, caption: node.properties["data-tutorial-caption"] || alt, locale })
        : createElement("a", { href: src, target: "_blank", rel: "noopener noreferrer", "aria-label": `${alt} · ${locale === "ko" ? "전체 크기로 보기" : "Open full size"}` }, createElement("img", { src, alt, title, loading: "lazy" })),
    },
    children: source,
  });
  return { content, codes, headings, images: [...new Set(images)], links };
}
