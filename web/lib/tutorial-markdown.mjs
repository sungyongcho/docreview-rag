import { createElement } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

export const DOCUMENTS = [
  { id: "walkthrough", locale: "ko", file: "ko/walkthrough.md", title: "첫 공시부터 인용 답변까지", label: "실습 가이드", href: "/docreview-rag-agent/docs/ko/" },
  { id: "cli", locale: "ko", file: "ko/cli.md", title: "로컬 실행 명령 안내", label: "CLI 명령 안내", href: "/docreview-rag-agent/docs/ko/cli/" },
  { id: "walkthrough", locale: "en", file: "en/walkthrough.md", title: "From your first filing to a cited answer", label: "Guided walkthrough", href: "/docreview-rag-agent/docs/en/" },
  { id: "cli", locale: "en", file: "en/cli.md", title: "Local command reference", label: "CLI reference", href: "/docreview-rag-agent/docs/en/cli/" },
];

function nodeText(node) {
  return node.value ?? (node.children ?? []).map(nodeText).join("");
}

export function renderTutorial(source, { locale = "ko", renderCode, assetVersion } = {}) {
  const documents = DOCUMENTS.filter((item) => item.locale === locale);
  const codes = [];
  const headings = [], images = [], links = [];
  const used = new Set();
  function prepare() {
    return (tree) => {
      const definitions = new Map(tree.children.filter((n) => n.type === "definition").map((n) => [n.identifier.toLowerCase(), n]));
      function visit(node) {
        if (node.type === "imageReference" || node.type === "linkReference") {
          const definition = definitions.get(node.identifier.toLowerCase());
          if (!definition) throw new Error(`Missing Markdown reference: ${node.identifier}`);
          node.type = node.type === "imageReference" ? "image" : "link";
          node.url = definition.url;
          node.title = definition.title;
        }
        if (node.type === "heading") {
          const text = nodeText(node);
          const base = text.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").trim().replace(/\s+/g, "-") || "section";
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
            const target = file ? documents.find((item) => item.file.split("/").pop() === file) : null;
            if (file && !target) throw new Error(`Unknown tutorial link: ${url}`);
            const hash = fragments.length ? decodeURIComponent(fragments.join("#")) : "";
            links.push({ file: target?.file ?? null, hash });
            node.url = `${target?.href ?? ""}${hash ? `#${encodeURIComponent(hash)}` : ""}`;
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
