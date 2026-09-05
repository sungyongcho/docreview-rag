# Ask a question and verify its citations

An answer joins source selection, retrieval, evidence review, and model execution. The result can be a
supported answer, insufficient evidence (`NOT_IN_DOCS`), or an operational failure. Read those outcomes
separately instead of treating every completed request as a successful answer.

## 9. Select an engine and ask the first question {#step-9}

- **Goal:** obtain an answer whose claims can be checked against the intended filing.
- **Prerequisites:** relevant evidence found in [step 8](retrieval.md#step-8), an available answer engine,
  and valid scoped filters. Reuse an existing result when you only need to learn the inspection controls.
- **Screen:** New review → controls above the question → Inspect request.
- **Inputs:** choose SEC scope, an available [engine](#engines), Balanced preset, and NVIDIA/FY2024 filters
  when those values are present in the catalog. Inspect the next request before sending.
- **Primary action:** **Send question**, using the example below.
- **Visible result:** actual execution phases arrive from the server, followed by an answer and evidence
  or an explicit failure. With Auto scope, server-confirmed routing appears only when supplied.
- **Completion:** the selected document/year is correct, the cited passages support the claims, and no
  operational failure is reported. `SUPPORTED` is a prompt to inspect evidence, not a substitute for it.
- **Recovery:** distinguish `NOT_IN_DOCS` from a provider failure, node error, or run limit. Open Run trace
  and use [runtime diagnosis](runtime.md) and [troubleshooting](troubleshooting.md).
- **Next:** [adjust settings and evidence choices](settings.md#step-10).

```text
What drove NVIDIA's data center revenue growth in FY2024? Cite evidence from the filing.
```

Sending may incur embedding, translation, and answer-model costs. The answer wording is not deterministic.
**Stop request** interrupts an active request. The UI never simulates completed stages or estimates time
remaining. Returning to an earlier phase can make later phases wait again.

<!-- capture:15-cited-answer -->

![An existing saved NVIDIA FY2024 answer and its retrieved source evidence are shown.](../assets/15-cited-answer.en.jpg)

*An existing saved NVIDIA FY2024 answer and its retrieved source evidence are shown. It was not rerun for this guide; candidate count and the single actual citation are distinct, and old evidence selections may be read-only.*

## Choose an answer engine {#engines}

The controls follow **corpus scope → answer engine/local model → retrieval preset → Review settings →
Inspect request**. Mobile keeps scope and engine selection visible. Engine availability and corpus readiness
are separate checks; a displayed model name does not prove it is installed or callable.

> [!DEV]
> Changing the answer engine/model or configuring a local server requires DEV. Normal public questions use the configured release policy and do not need these controls.

OpenAI uses the configured answer policy and a valid local development key. Inspect current model IDs in
[CLI configuration](cli.md#installation-and-configuration); do not change a model or budget just to make
an execution appear quicker.

For Ollama, open **Settings → Local LLM**. Keep a working connection; otherwise select **Default** and use **Run connection diagnostics** to inspect the backend connection and answer-model availability. Choose **Connect** only when you intend to apply that server, then select an installed answer-capable model in the conversation. **Add a server…** is for a named alternate endpoint, not a required setup step.

The [macOS/Linux Ollama guide](ollama.md#connect) explains installation, network access, and recovery. Diagnostics do not generate an answer or load a model. Embedding-only models cannot answer questions; a production preview can intentionally disable local models. See [settings](settings.md#local-server) and [runtime](runtime.md#local-models) for the configuration and measured-state boundaries.

## Inspect scope, evidence, and the request {#inspection}

The scope/preset question-mark controls respond to hover, focus, touch, and Escape. Auto keeps the selected
scope separate from the actual registry, companies, fiscal years, and reason returned by the server.
Before resolution it is unconfirmed; the browser does not invent that decision.

Use **Review settings** to edit Filters, Search, Evidence, or Run limits in one independent editor.
Choosing Custom opens its Search section directly. Close the editor before using the separate
**Inspect request** icon and short label in the primary control row; it only reads the next request.

Inspect request is a side drawer on wide screens and a full-screen dialog on narrow
screens. It scrolls independently and returns focus when closed. It separates retrieval, filters, engine,
prompt composition, and outgoing payload. Evidence is unresolved before execution; server-applied values
belong to the resulting execution record, when collected.

Expand **Retrieved evidence candidates** and read document identity, year, source links, and excerpts.
Candidate count and citation count measure different things. Pin/Exclude choices apply only when you
[review again with selected evidence](settings.md#step-10); they do not rewrite the current answer.

Use **View corpus readiness** to inspect preparation and **Back to conversation** to return to the retained
draft, profile, messages, and scroll. [Execution performance](runtime.md) explains measured bars, repeated
calls, uncollected fields, and legacy records.
