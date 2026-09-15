/** Convert the manual's narrow authoring markers into safe Markdown containers. */
export function prepareTutorialStructure(tree) {
  const detailIds = new Set();

  function children(nodes, insideDetails = false) {
    const result = [];
    let aliases = [];
    for (let index = 0; index < nodes.length; index += 1) {
      const node = nodes[index];
      const marker = node.type === "html" ? node.value.trim() : "";
      const alias = marker.match(/^<!-- heading-alias: ([\p{L}\p{N}-]+) -->$/u);
      if (alias) { aliases.push(alias[1]); continue; }
      const details = marker.match(/^<!-- details: ([a-z][a-z0-9-]*) \| (.+) -->$/);
      if (details) {
        if (insideDetails) throw new Error("Tutorial details cannot be nested");
        if (aliases.length) throw new Error("Heading aliases must precede a heading");
        if (detailIds.has(details[1])) throw new Error(`Duplicate tutorial details: ${details[1]}`);
        detailIds.add(details[1]);
        let end = index + 1;
        while (end < nodes.length && !(nodes[end].type === "html" && nodes[end].value.trim() === "<!-- /details -->")) end += 1;
        if (end === nodes.length) throw new Error(`Unclosed tutorial details: ${details[1]}`);
        result.push({
          type: "blockquote",
          data: { hName: "details", hProperties: { id: `detail-${details[1]}`, className: ["docs-details"], "data-doc-detail": details[1] } },
          children: [
            { type: "paragraph", data: { hName: "summary" }, children: [{ type: "text", value: details[2].trim() }] },
            ...children(nodes.slice(index + 1, end), true),
          ],
        });
        index = end;
        continue;
      }
      if (marker === "<!-- /details -->") throw new Error("Unexpected tutorial details closing marker");
      if (/^<!-- (?:details:|heading-alias:)/.test(marker)) throw new Error(`Invalid tutorial marker: ${marker}`);
      if (aliases.length) {
        if (node.type !== "heading") throw new Error("Heading aliases must precede a heading");
        node.data = { ...node.data, hProperties: { ...node.data?.hProperties, "data-heading-aliases": aliases } };
        aliases = [];
      }
      if (node.children) node.children = children(node.children, insideDetails);
      result.push(node);
    }
    if (aliases.length) throw new Error("Heading aliases must precede a heading");
    return result;
  }

  tree.children = children(tree.children);
}
