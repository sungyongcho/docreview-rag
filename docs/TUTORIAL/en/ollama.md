# Set up Ollama on macOS and Linux

> [!DEV]
> Connecting and configuring a local answer server in DocReview requires DEV. Installation and service commands are performed by the owner of that computer.

Use this guide when **Settings → Local LLM** cannot find an answer model, or when you want to connect a separately installed Ollama server. Finish [environment setup](environment.md#step-1) first. A prepared DocReview corpus can be reused; installing Ollama does not rebuild documents or embeddings.

The commands below are for you to run deliberately. Reading this page or opening the guide does not install software, download models, change services, or send a question to a model.

## Check what already exists {#check}

Run these on the computer that should host Ollama:

```bash
command -v ollama
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:11434/api/tags
```

An HTTP response containing a `models` array confirms the local API responded. An empty array means no models were listed; it does not mean the server is down. If this succeeds, skip installation and continue with [model selection](#models). The standard API port is **11434**. [Ollama API introduction](https://docs.ollama.com/api/introduction), [List models](https://docs.ollama.com/api/tags).

## Install and start on macOS {#macos}

The current official requirements are macOS 14 or newer. Download the installer from the [official macOS instructions](https://docs.ollama.com/macos), open the DMG, move Ollama to Applications, and open the app. Follow its prompt to make the CLI available if needed.

```bash
open -a Ollama
ollama --version
```

Repeat the [API check](#check). When the app already serves port 11434, do not also start `ollama serve`: a second process cannot own the same listening address. For a failed app start, inspect the recent server log:

```bash
tail -n 80 ~/.ollama/logs/server.log
```

The log location is documented in [Ollama troubleshooting](https://docs.ollama.com/troubleshooting). A Mac model name or processor family alone does not establish where a particular run executed.

## Install and start on Linux {#linux}

If `ollama` is absent, the [official Linux installation](https://docs.ollama.com/linux) uses this installer. It installs software and may require administrator privileges:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Inspect a systemd installation first:

```bash
systemctl status ollama --no-pager
```

If the installed service is stopped and you want it running, start it explicitly:

```bash
sudo systemctl start ollama
```

For an installation without a systemd service, start `ollama serve` in a terminal and leave that terminal open. Use one server process. Repeat the [API check](#check) from another terminal. The official page covers manual installation when the installer does not suit your machine.

```bash
ollama serve
```

Read recent service logs without changing anything:

```bash
journalctl -u ollama -n 80 --no-pager
```

For a foreground server, read the terminal where it runs. [Ollama troubleshooting](https://docs.ollama.com/troubleshooting).

## Let the DocReview backend reach the server {#network}

The browser talks to the DocReview backend; that backend connects to Ollama. A successful host-terminal check therefore does not prove that the backend container can reach the same server.

| DocReview backend location | Default server address seen by DocReview |
| --- | --- |
| Native process on the Ollama computer | `http://127.0.0.1:11434` |
| Repository Docker development stack, Ollama on its host | `http://host.docker.internal:11434` |
| A different computer or a custom server | Use **Add a server…** with the address reachable from that backend |

Keep **Default** selected; DocReview resolves the address for this environment. Addresses appear only under **Connection details** for diagnostics. The repository Docker configuration supplies the host-gateway mapping; inside a container, `127.0.0.1` refers to that container. Add a server only for an intentional alternate endpoint; enter its origin without `/api` or `/v1` when using Ollama auto detection.

Ollama normally listens only on host loopback. If backend diagnostics show that the container cannot reach it, a different listening address may be necessary. The following examples listen on **all interfaces**, so use them only with a trusted network boundary that restricts access to the intended clients. Do not expose this unauthenticated local API directly to the Internet. [Ollama server configuration](https://docs.ollama.com/faq), [API authentication](https://docs.ollama.com/api/authentication).

### macOS app listening address {#macos-bind}

After checking that no Ollama work is active, set the app environment, then quit and reopen the Ollama app:

```bash
launchctl setenv OLLAMA_HOST 0.0.0.0:11434
```

Changing an environment variable in an unrelated terminal does not reconfigure an already running macOS app. [Official macOS environment procedure](https://docs.ollama.com/faq#setting-environment-variables-on-mac).

### Linux systemd listening address {#linux-bind}

Open the service override and add the setting under `[Service]`, preserving any existing entries:

```bash
sudo systemctl edit ollama.service
```

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

After checking that no Ollama work is active, apply the override explicitly:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama.service
```

For a foreground server, stop that server deliberately before starting it with `OLLAMA_HOST=0.0.0.0:11434 ollama serve`. Run the host API check and DocReview diagnostics again afterward. [Official Linux environment procedure](https://docs.ollama.com/faq#setting-environment-variables-on-linux).

## Install or inspect an answer model {#models}

List installed models first:

```bash
ollama ls
```

Reuse a suitable installed answer model. If none exists, choose a local chat/completion model and exact tag from the [official model library](https://ollama.com/library), checking its license and storage needs. Download only after making that choice:

```bash
# Replace this with the exact model tag you chose.
ollama pull 'MODEL_TAG_FROM_LIBRARY'
```

`pull` downloads model files; it does not run a test question. It can use substantial network traffic and disk space. A cloud model entry is not evidence that its weights are installed locally. [Ollama CLI reference](https://docs.ollama.com/cli).

Inspect an installed model without generating text:

```bash
# Replace this with an exact name from ollama ls.
ollama show 'MODEL_NAME_FROM_LIST'
ollama ps
```

| Information | What it means |
| --- | --- |
| Installed size | Model file size reported by the server; not RAM needed for a run |
| Parameters and quantization | Model metadata, when supplied |
| Maximum context | Model metadata limit; not the context currently allocated to a run |
| Loaded context | Current runtime allocation, only when the loaded-model API reports it |
| Answer capability | Whether the server reports a capability DocReview accepts for answers |
| Not loaded | Normal standby for an installed model; it does not imply failure |

`/api/show` supplies model details; `/api/ps` reports currently loaded models. DocReview's current model list does not collect the maximum or loaded context values: inspect those through Ollama's own tools. Missing fields remain unknown. A larger context allocation generally needs more memory; this guide does not change your selected model, context, or budgets. See [model details](https://docs.ollama.com/api-reference/show-model-details), [loaded models](https://docs.ollama.com/api/ps), and [context length](https://docs.ollama.com/context-length).

## Connect in DocReview {#connect}

Open **Settings → Local LLM** and use the server selector. **Default** obtains its address from the current DocReview environment. **Add a server…** reveals a server name, alternate address, and protocol. The name is a label that helps you recognize this endpoint later.

<!-- capture:13-local-model -->

![Default resolves the configured local Ollama endpoint without an address field.](../assets/13-local-model.en.jpg)

*Default resolves the configured local Ollama endpoint without an address field. Actual connection health, three installed models and one answer-capable model are distinguished; addresses remain in Connection details.*

Select **Run connection diagnostics** first. Its title identifies the candidate being checked; the active connection remains unchanged. Check the backend-to-server result and answer-model status, and open **Connection details** to inspect the active/default addresses. Use **Connect** for an existing choice or **Add & connect** for a new server only when you intend to apply it. A failed probe or save keeps the prior working configuration. Connecting an answer server does not change the embedding provider.

<!-- capture:25-add-server -->

![Add a server reveals name, URL and protocol fields.](../assets/25-add-server.en.jpg)

*Add a server reveals name, URL and protocol fields. This unsubmitted draft keeps Add & connect disabled while the existing Default connection remains active.*

**Disconnect** disables local answers. **Use Default** checks the startup server before switching and keeps added servers. If that check or save fails, the current working connection remains active.

Return to the conversation and select the installed model in the answer-engine control. A connection check does not submit your draft question. Continue with [answers](answers.md#engines) and [request settings](settings.md#step-10) when you are ready to ask a question.

## Run read-only diagnostics {#diagnostics}

After [registering the project commands](cli.md#register-commands-and-open-help), run:

```bash
rag-ollama-check
rag-ollama-check --web-url http://localhost:8000
rag-ollama-check --details
rag-ollama-check --setup
```

The first command uses the configured web address. Set `--web-url` only when using another frontend address; it is not an Ollama URL. `--details` exposes additional host/container and listener evidence. `--setup` prints manual setup instructions. The diagnostics do not install Ollama, change settings, download or load a model, or generate an answer.

Read failures by layer rather than repeating installation:

| Symptom | Evidence to check | Recovery and verification |
| --- | --- | --- |
| Host API does not respond | App/service state and server logs | Start the intended server, then repeat `/api/tags` |
| Host works; backend fails | Backend result, listening address, host gateway, firewall | Correct the reachable address or approved bind settings; rerun diagnostics |
| Backend works; no answer models | Installed list and reported capabilities | Choose/install a suitable model, then refresh discovery |
| Installed but not loaded | Installed model present; loaded list empty | Standby is normal; no extra warm-up is required |
| Connection is disabled in production | Runtime mode and permission diagnosis | Use the development environment; do not bypass public permissions |
| Connection save fails | The save error and prior active configuration | Keep the working setting, resolve the reported cause, then retry explicitly |
| Answer fails after connection succeeds | Run trace and the recorded failure type | Follow [execution troubleshooting](troubleshooting.md#execution); reachability is not an answer-quality test |

For logs and measured execution, continue with [runtime](runtime.md#local-models). The [CLI reference](cli.md#diagnose-local-model-connectivity) owns the full diagnostic-command details.

<!-- capture:24-connection-diagnostics -->

![A real read-only Default connection check passed server selection, connectivity and answer-model availability.](../assets/24-connection-diagnostics.en.jpg)

*A real read-only Default connection check passed server selection, connectivity and answer-model availability. No settings, models or services were changed.*
