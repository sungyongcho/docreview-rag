import { createElement } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DOCUMENTATION_REGISTRY, documentationDocuments, documentationLink } from "./documentation-registry.mjs";
export { DOCUMENTS } from "./documentation-registry.mjs";

function nodeText(node) {
  return node.value ?? (node.children ?? []).map(nodeText).join("");
}

export function renderTutorial(source, { locale = "ko", renderCode, assetVersion, registry = DOCUMENTATION_REGISTRY } = {}) {
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
        if (node.children) node.children = node.children.map((child) => child.type === "html" && child.value.trim() === "<!-- tutorial-steps -->" ? {
          type: "list", ordered: true, start: 1, spread: false,
          children: steps.map((step) => ({ type: "listItem", spread: false, children: [{ type: "paragraph", children: [{ type: "link", url: `${step.source}#${step.anchor}`, children: [{ type: "text", value: step.title }] }] }] })),
        } : child);
        if (node.type === "imageReference" || node.type === "linkReference") {
          const definition = definitions.get(node.identifier.toLowerCase());
          if (!definition) throw new Error(`Missing Markdown reference: ${node.identifier}`);
          node.type = node.type === "imageReference" ? "image" : "link";
          node.url = definition.url;
          node.title = definition.title;
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
    remarkPlugins: [remarkGfm, prepare],
    components: {
      ...(renderCode ? { pre: ({ children }) => renderCode(codes[Number(children.props["data-code-index"])]) } : {}),
      ...Object.fromEntries([1, 2, 3, 4, 5, 6].map((depth) => [`h${depth}`, ({ children, id }) => createElement(`h${depth}`, { id }, createElement("a", { href: `#${encodeURIComponent(id)}`, className: "docs-heading-link" }, children, createElement("span", { "aria-hidden": true, className: "docs-heading-hash" }, " #")))])),
      table: ({ children }) => createElement("div", { className: "markdown-table-wrap", tabIndex: 0, role: "region", "aria-label": locale === "ko" ? "가로로 스크롤할 수 있는 표" : "Scrollable table" }, createElement("table", null, children)),
      img: ({ src, alt, title }) => createElement("a", { href: src, target: "_blank", rel: "noopener noreferrer", "aria-label": `${alt} · ${locale === "ko" ? "전체 크기로 보기" : "Open full size"}` }, createElement("img", { src, alt, title, loading: "lazy" })),
    },
    children: source,
  });
  return { content, codes, headings, images: [...new Set(images)], links };
}
