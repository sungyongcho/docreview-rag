"use client";

import { useState } from "react";
import { acknowledgeWipeBrowser, getWipeStatus, operatorAvailable } from "@/lib/operator-api";
import { clearExtremeBrowserData } from "@/lib/reset-browser";

export default function ResetLocalPage() {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function clear() {
    setBusy(true);
    try {
      const id = window.location.hash.slice(1);
      const status = await getWipeStatus();
      if (!id || status.id !== id || !status.extreme || status.status !== "running" || status.stage !== "awaiting_browser") {
        throw new Error("No matching extreme reset is waiting. Return to the terminal; do not start another reset.");
      }
      clearExtremeBrowserData(localStorage, sessionStorage);
      const receipt = await acknowledgeWipeBrowser(id);
      if (!receipt.acknowledged || receipt.id !== id) throw new Error("Acknowledgement mismatch");
      setMessage(`DocReview browser data deleted for ${window.location.origin}. The terminal received acknowledgement. Other browsers and origins are unchanged. Close this page; services will stop.`);
    } catch {
      setMessage("Deletion or acknowledgement could not be confirmed. Browser data may already be cleared. Check the terminal reset status before any resubmission.");
    } finally { setBusy(false); }
  }
  return <main style={{ maxWidth: 720, margin: "3rem auto", padding: "1rem" }}>
    <h1>Extreme reset: browser data</h1>
    <p>Close every other DocReview tab before continuing so an open conversation cannot save itself again. This clears DocReview conversations, preferences and session data in this browser at this exact address. Unrelated website storage is preserved.</p>
    <p>No backup is created. The application cannot restore deleted data. The terminal must already have received both extreme-reset confirmations.</p>
    <button type="button" disabled={busy || !operatorAvailable() || message.startsWith("DocReview browser data deleted")} onClick={() => void clear()}>Delete this browser’s DocReview data and acknowledge</button>
    <p role="status">{message}</p>
  </main>;
}
