import { createElement } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { ArrowRight, BarChart3, Database, FileSearch, MessageSquare, Terminal } from "lucide-react";
import { tutorialControlParts } from "./tutorial-controls.mjs";
import { prepareTutorialStructure } from "./tutorial-structure.mjs";
import { DOCUMENTATION_REGISTRY, documentationDocuments, documentationLink } from "./documentation-registry.mjs";
export { DOCUMENTS } from "./documentation-registry.mjs";

// These entry points only navigate to the app; none submits a question or starts a job.
const APP_GUIDE_LINKS = new Set(["/docreview-rag/?view=review", "/docreview-rag/?view=build&tab=documents", "/docreview-rag/?view=measure&tab=compare"]);

function nodeText(node) {
  return node.value ?? (node.children ?? []).map(nodeText).join("");
}

const STATUS_BADGES = [
  { id: "supported", en: "Supported", ko: "근거 확인", terms: ["SUPPORTED"] },
  { id: "not-in-docs", en: "Not in documents", ko: "문서에서 근거를 찾지 못함", terms: ["NOT_IN_DOCS", "Not in documents", "문서에서 근거를 찾지 못함", "문서에 없음"] },
  { id: "unsupported", en: "Unsupported request", ko: "지원하지 않는 요청", terms: ["Unsupported request", "지원하지 않는 요청"] },
  { id: "empty-scope", en: "Empty scope", ko: "빈 문서 범위", terms: ["Empty scope", "빈 문서 범위"] },
  { id: "scope-conflict", en: "Scope conflict", ko: "문서 범위 충돌", terms: ["Scope conflict", "문서 범위 충돌"] },
  { id: "clarification", en: "Company clarification needed", ko: "기업 확인 필요", terms: ["Company clarification needed", "기업 확인 필요"] },
  { id: "not-generated", en: "Answer not generated", ko: "답변 미생성", terms: ["Answer not generated", "답변 미생성"] },
];

/** Transform exact status mentions in prose, without touching code, anchors or link labels. */
function statusBadgePlugin(locale) {
  const terms = new Map(STATUS_BADGES.flatMap((badge) => badge.terms.map((term) => [term, badge])));
  const pattern = new RegExp(`(?<![A-Za-z0-9_])(${[...terms.keys()].sort((a, b) => b.length - a.length).join("|")})(?![A-Za-z0-9_])`, "g");
  const badgeNode = (badge) => ({ type: "emphasis", data: { hName: "span", hProperties: { className: ["docs-status-badge", `is-${badge.id}`], "data-status": badge.id } }, children: [{ type: "text", value: badge[locale] }] });
  return () => (tree) => {
    /** Match Korean particles to the displayed label rather than the replaced ASCII token. */
    function trailingBadge(node) {
      if (node?.data?.hProperties?.["data-status"]) return nodeText(node);
      return ["strong", "emphasis"].includes(node?.type) ? trailingBadge(node.children?.at(-1)) : null;
    }
    function visit(node) {
      if (["code", "html", "heading", "link", "linkReference", "definition", "image", "imageReference", "math", "inlineMath"].includes(node.type) || !node.children) return;
      if (node.type === "tableCell" && node.children.length === 1 && node.children[0].type === "text" && tutorialControlParts(node.children[0].value)) {
        node.children = [{ type: "strong", children: node.children }];
      }
      if (node.type === "strong") {
        const text = nodeText(node);
        if (node.children.every((child) => child.type === "text") && tutorialControlParts(text)) node.data = { ...node.data, hProperties: { ...node.data?.hProperties, "data-tutorial-control": text } };
      }
      node.children = node.children.flatMap((child) => {
        if (child.type === "inlineCode") return terms.has(child.value) ? [badgeNode(terms.get(child.value))] : [child];
        if (child.type !== "text") { visit(child); return [child]; }
        const result = [];
        let offset = 0;
        for (const match of child.value.matchAll(pattern)) {
          if (match.index > offset) result.push({ type: "text", value: child.value.slice(offset, match.index) });
          result.push(badgeNode(terms.get(match[0])));
          offset = match.index + match[0].length;
        }
        if (offset < child.value.length) result.push({ type: "text", value: child.value.slice(offset) });
        return result;
      });
      if (locale === "ko") node.children.forEach((child, index) => {
        const label = trailingBadge(node.children[index - 1]);
        if (!label || child.type !== "text") return;
        const final = label.charCodeAt(label.length - 1) - 0xac00;
        if (final < 0 || final > 11171) return;
        const consonant = final % 28;
        child.value = child.value.replace(/^(으로|로|은|는|이|가|을|를|과|와)(?=[\s.,!?·:;]|$)/, (particle) => {
          if (["으로", "로"].includes(particle)) return consonant && consonant !== 8 ? "으로" : "로";
          const pair = [["은", "는"], ["이", "가"], ["을", "를"], ["과", "와"]].find((items) => items.includes(particle));
          return pair[consonant ? 0 : 1];
        });
      });
    }
    visit(tree);
  };
}

export function renderTutorial(source, { locale = "ko", renderCode, renderDevelopmentNotice, renderImage, assetVersion, imageDimensions = {}, math = false, statusBadges = false, overviewLayout = false, registry = DOCUMENTATION_REGISTRY } = {}) {
  const steps = documentationDocuments(registry)
    .filter((document) => document.locale === locale)
    .flatMap((document) => document.steps.map((step) => ({ ...step, source: document.source })))
    .sort((a, b) => a.number - b.number);
  const codes = [];
  const headings = [], images = [], links = [], captures = [];
  const used = new Set();
  /** Registry-backed step groups preserve every canonical destination and step number. */
  function learningPath() {
    const phases = [
      { range: [1, 2], title: locale === "ko" ? "환경과 자료 확인" : "Check your starting point", description: locale === "ko" ? "설치 상태와 이미 준비된 자료를 먼저 확인합니다." : "Inspect the environment and the data already available." },
      { range: [3, 7], title: locale === "ko" ? "검색할 근거 준비" : "Prepare the evidence", description: locale === "ko" ? "필요한 공시만 모으고 검색 인덱스를 준비합니다." : "Acquire the missing filings and prepare the search indexes." },
      { range: [8, 12], title: locale === "ko" ? "질문·검증·비교" : "Ask, verify and compare", description: locale === "ko" ? "검색과 답변을 확인하고 평가 결과를 비교합니다." : "Inspect retrieval and answers, then compare evaluation results." },
    ];
    return { type: "list", ordered: false, spread: true, data: { hProperties: { className: ["guide-learning-groups"] } }, children: phases.map((phase) => ({
      type: "listItem", spread: true, data: { hProperties: { className: ["guide-learning-group"] } }, children: [
        { type: "paragraph", data: { hProperties: { className: ["guide-phase-title"] } }, children: [{ type: "strong", children: [{ type: "text", value: phase.title }] }] },
        { type: "paragraph", children: [{ type: "text", value: phase.description }] },
        { type: "list", ordered: true, start: phase.range[0], spread: false, data: { hProperties: { className: ["guide-step-list"] } }, children: steps.filter((step) => step.number >= phase.range[0] && step.number <= phase.range[1]).map((step) => ({
          type: "listItem", spread: false, data: { hProperties: { "data-guide-step": String(step.number) } }, children: [{ type: "paragraph", children: [{ type: "link", url: `${step.source}#${step.anchor}`, children: [{ type: "text", value: step.title }] }] }],
        })) },
      ],
    })) };
  }
  function prepare() {
    return (tree) => {
      prepareTutorialStructure(tree);
      const definitions = new Map(tree.children.filter((n) => n.type === "definition").map((n) => [n.identifier.toLowerCase(), n]));
      function visit(node) {
        if (overviewLayout && node.children) {
          node.children.forEach((child, index) => {
            if (child.type !== "html" || !["<!-- guide-features -->", "<!-- guide-local-paths -->"].includes(child.value.trim())) return;
            const list = node.children[index + 1];
            if (list?.type !== "list") throw new Error("Guide cards must be followed by a Markdown list");
            const features = child.value.trim() === "<!-- guide-features -->";
            list.data = { hProperties: { className: [features ? "guide-feature-cards" : "guide-local-cards"] } };
            const icons = features ? ["question", "evidence", "compare"] : ["terminal", "database"];
            list.children.forEach((item, itemIndex) => { item.data = { hProperties: { "data-guide-icon": icons[itemIndex] } }; });
          });
        }
        for (const [index, child] of (node.children ?? []).entries()) {
          const capture = child.type === "html" && child.value.trim().match(/^<!-- screenshot: ([a-z][a-z0-9-]*) -->$/);
          if (capture) {
            captures.push(capture[1]);
            const next = node.children[index + 1];
            const image = next?.type === "paragraph" && next.children.length === 1 ? next.children[0] : null;
            if (image?.type === "image" || image?.type === "imageReference") image.data = { ...image.data, hProperties: { ...image.data?.hProperties, "data-capture-id": capture[1] } };
          }
          const picture = child.type === "paragraph" && child.children.length === 1 ? child.children[0] : null;
          const following = node.children[index + 1];
          if ((picture?.type === "image" || picture?.type === "imageReference") && following?.type === "paragraph" && following.children.length === 1 && following.children[0].type === "emphasis") {
            picture.data = { ...picture.data, hProperties: { ...picture.data?.hProperties, "data-tutorial-caption": nodeText(following) } };
          }
        }
        if (node.children) node.children = node.children.map((child) => child.type === "html" && child.value.trim() === "<!-- tutorial-steps -->" ? overviewLayout ? learningPath() : {
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
          const stepNumber = explicit?.[1].match(/^step-(\d+)$/)?.[1];
          if (stepNumber && node.children[0]?.type === "text") node.children[0].value = node.children[0].value.replace(new RegExp(`^${stepNumber}\\.\\s+`), "");
          const text = nodeText(node);
          const base = explicit?.[1] ?? (text.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").trim().replace(/\s+/g, "-") || "section");
          if (explicit && used.has(base)) throw new Error(`Duplicate explicit tutorial heading: ${base}`);
          let id = base;
          for (let suffix = 2; used.has(id); suffix += 1) id = `${base}-${suffix}`;
          used.add(id);
          const aliases = (node.data?.hProperties?.["data-heading-aliases"] ?? []).filter((alias) => alias !== id);
          for (const alias of aliases) {
            if (used.has(alias)) throw new Error(`Duplicate tutorial heading alias: ${alias}`);
            used.add(alias);
            headings.push({ id: alias, text, depth: 0, aliasFor: id });
          }
          node.data = { ...node.data, hProperties: { id, "data-heading-aliases": aliases, ...(stepNumber ? { "data-doc-step": stepNumber } : {}) } };
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
          if (imageDimensions[path]) node.data = { ...node.data, hProperties: { ...node.data?.hProperties, ...imageDimensions[path] } };
          node.url = `/docreview-rag/tutorial-assets/${path.slice(7).split("/").map(encodeURIComponent).join("/")}`;
          if (assetVersion) node.url += `?v=${encodeURIComponent(assetVersion)}`;
        }
        if (node.type === "link") {
          const url = node.url;
          if (!/^(https?:|mailto:)/i.test(url) && !APP_GUIDE_LINKS.has(url)) {
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
    remarkPlugins: [remarkGfm, ...(math ? [remarkMath] : []), prepare, ...(statusBadges ? [statusBadgePlugin(locale)] : [])],
    rehypePlugins: math ? [rehypeKatex] : [],
    components: {
      strong: ({ children, node }) => {
        const parts = tutorialControlParts(node.properties["data-tutorial-control"] ?? "");
        if (!parts) return createElement("strong", null, children);
        return createElement("span", { className: "docs-control-path" }, parts.flatMap(({ Icon, label }, index) => [
          ...(index ? [createElement("span", { className: "docs-control-separator", key: `separator-${index}`, "aria-hidden": true }, " → ")] : []),
          createElement("span", { className: "docs-control-label", key: label }, Icon ? createElement(Icon, { size: 17, "aria-hidden": true }) : null, createElement("span", null, label)),
        ]));
      },
      li: ({ children, node, ...props }) => {
        const icon = node.properties["data-guide-icon"];
        const step = node.properties["data-guide-step"];
        const Icon = { question: MessageSquare, evidence: FileSearch, compare: BarChart3, terminal: Terminal, database: Database }[icon];
        if (Icon) return createElement("li", { className: "guide-route-card" }, createElement(Icon, { className: "guide-route-icon", size: 21, "aria-hidden": true }), createElement("div", { className: "guide-route-content" }, children));
        if (step) return createElement("li", { className: "guide-step", value: Number(step) }, createElement("span", { className: "guide-step-number", "aria-hidden": true }, String(step).padStart(2, "0")), children, createElement(ArrowRight, { size: 13, "aria-hidden": true }));
        return createElement("li", props, children);
      },
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
      ...Object.fromEntries([1, 2, 3, 4, 5, 6].map((depth) => [`h${depth}`, ({ children, id, node }) => {
        if (node?.properties?.["data-screenshot-needed"] === "true") return null;
        const step = node?.properties?.["data-doc-step"];
        return createElement(`h${depth}`, { id, "data-doc-section": id },
          ...(node?.properties?.["data-heading-aliases"] ?? []).map((alias) => createElement("span", { key: alias, id: alias, "data-doc-alias": id, className: "docs-heading-alias", "aria-hidden": true })),
          step ? createElement("span", { className: "docs-learning-step" }, locale === "ko" ? `전체 학습 경로 · ${step}/${steps.length}` : `Learning path · ${step}/${steps.length}`) : null,
          createElement("a", { href: `#${encodeURIComponent(id)}`, className: "docs-heading-link" }, children, createElement("span", { "aria-hidden": true, className: "docs-heading-hash" }, " #")));
      }])),
      table: ({ children }) => createElement("div", { className: "markdown-table-wrap", tabIndex: 0, role: "region", "aria-label": locale === "ko" ? "가로로 스크롤할 수 있는 표" : "Scrollable table" }, createElement("table", null, children)),
      img: ({ src, alt, title, node }) => renderImage
        ? renderImage({ src, alt, title, caption: node.properties["data-tutorial-caption"] || alt, locale, width: node.properties.width, height: node.properties.height, captureId: node.properties["data-capture-id"] })
        : createElement("a", { href: src, target: "_blank", rel: "noopener noreferrer", "aria-label": `${alt} · ${locale === "ko" ? "전체 크기로 보기" : "Open full size"}` }, createElement("img", { src, alt, title, loading: "lazy" })),
    },
    children: source,
  });
  return { content, codes, headings, images: [...new Set(images)], links, captures };
}
