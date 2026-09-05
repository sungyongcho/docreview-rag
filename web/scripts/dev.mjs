import { spawn } from "node:child_process";
import { watchTutorial } from "./tutorial-watch.mjs";

// This entrypoint runs only for `npm run dev`; exported deployments have no watcher.
const stop = await watchTutorial();
const next = spawn(process.execPath, ["node_modules/next/dist/bin/next", "dev", ...process.argv.slice(2)], { stdio: "inherit" });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => next.kill(signal));
next.on("error", async (error) => { console.error(error); await stop(); process.exitCode = 1; });
next.on("exit", async (code) => { await stop(); process.exitCode = code ?? 1; });
