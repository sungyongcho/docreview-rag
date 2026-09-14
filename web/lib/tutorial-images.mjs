import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** Reserve the intrinsic size of canonical PNG captures before client hydration. */
export function tutorialImageDimensions(root, paths) {
  return Object.fromEntries(paths.filter((path) => path.endsWith(".png")).map((path) => {
    const bytes = readFileSync(resolve(root, path));
    if (bytes.length < 24 || bytes.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a") throw new Error(`Invalid tutorial PNG: ${path}`);
    const width = bytes.readUInt32BE(16), height = bytes.readUInt32BE(20);
    if (!width || !height) throw new Error(`Invalid tutorial PNG dimensions: ${path}`);
    return [path, { width, height }];
  }));
}
