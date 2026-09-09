"use client";

import { PrepareLocalModel } from "./prepare-local-model";
import type { ReviewEngineState } from "@/lib/types";
import { ArrowRight } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { AnswerEngineState } from "@/lib/answer-engine-state";
import "./answer-engine-light.css";

/** Shared, labelled status light; the reason remains available without colour. */
export function AnswerEngineLight({ engine, showStatus = false }: { engine: AnswerEngineState; showStatus?: boolean }) {
  const { t } = useI18n();
  const text = `${t(engine.label)}: ${t(engine.reason)}`;
  return <span className="answer-engine-light" data-engine={engine.id} data-light={engine.light} title={showStatus ? undefined : text} aria-label={text}><i aria-hidden="true" />{t(engine.label)}{showStatus && <>: {t(engine.light === "green" ? "Ready" : engine.reason)}</>}</span>;
}

/** Show each engine's actual metadata and its own configuration destination. */
export function AnswerEngineRows({ engines, onOpenStatus, onOpenLocal, onLocalPrepared }: { onLocalPrepared?: (local: ReviewEngineState) => void; engines: AnswerEngineState[]; onOpenStatus: () => void; onOpenLocal?: () => void }) {
  const { t } = useI18n();
  return <div className="answer-engine-rows">{engines.map((engine) => <section className="answer-engine-row" key={engine.id} aria-label={t(engine.label)}>
    <strong><AnswerEngineLight engine={engine} /></strong><span>{t(engine.reason)}</span>
    <dl><div><dt>{t("Model")}</dt><dd>{engine.model ?? t("Not configured")}</dd></div>
      {engine.id === "openai" ? <div><dt>{t("Key slot")}</dt><dd>{engine.keySlot ?? t("Not configured")}</dd></div> : <>
        <div><dt>{t("Server")}</dt><dd>{engine.server ?? t("Not configured")}</dd></div>
        <div><dt>{t("CPU / GPU placement")}</dt><dd>{engine.placement === "cpu" ? "CPU" : engine.placement === "gpu" ? "GPU" : engine.placement === "mixed" ? "CPU + GPU" : t("Placement unknown")}</dd></div>
        <div><dt>{t("Last measured speed")}</dt><dd>{engine.speed == null ? t("Not measured") : `${engine.speed.toFixed(1)} tok/s`}</dd></div>
      </>}
    </dl>{engine.id === "local" && engine.server === "Ollama" && <PrepareLocalModel model={engine.model} ready={["Ready to answer", "Slow CPU (below 15 tok/s)"].includes(engine.reason)} onPrepared={(value) => onLocalPrepared?.(value.local)} />}<button className="button answer-engine-action" type="button" onClick={engine.id === "openai" ? onOpenStatus : onOpenLocal} disabled={engine.id === "local" && !onOpenLocal}>{t(engine.id === "openai" ? "Open System status" : "Open Local LLM settings")}<ArrowRight size={16} aria-hidden="true" /></button>
  </section>)}</div>;
}
