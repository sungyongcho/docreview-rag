/** Split one GitHub-readable source into the DEV introduction, CLI/Web tabs, and handoff. */
export function splitQuickStart(source) {
  const markers = ["<!-- quickstart-cli -->", "<!-- quickstart-web -->", "<!-- quickstart-end -->"];
  let remaining = source;
  const pieces = [];
  for (const marker of markers) {
    if (remaining.split(marker).length !== 2) throw new Error(`Quick Start requires exactly one ${marker}`);
    const index = remaining.indexOf(marker);
    pieces.push(remaining.slice(0, index));
    remaining = remaining.slice(index + marker.length);
  }
  return { common: pieces[0], cli: pieces[1], web: pieces[2], after: remaining };
}
