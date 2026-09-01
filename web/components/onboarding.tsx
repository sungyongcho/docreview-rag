"use client";

import { ArrowLeft, ArrowRight, X } from "lucide-react";
import { useState } from "react";

const STEPS = [
  ["Start a grounded review", "Ask in the center. DocReview retrieves filing evidence before answering."],
  ["Verify every citation", "Expand evidence to inspect document identity, source span, and exact text."],
  ["Continue earlier reviews", "Recent reviews and their retrieval profiles remain in this browser."],
  ["Experiment in Corpus Lab", "Run golden suites, compare parameters, and inspect the exact API payload."],
  ["Open the documentation", "The separate documentation window will hold architecture and build chapters."],
] as const;

export function Onboarding({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0);
  const [title, description] = STEPS[step];

  return (
    <div className="tour-scrim" role="presentation">
      <section className="tour-dialog" role="dialog" aria-modal="true" aria-labelledby="tour-title">
        <button className="icon-button tour-x" type="button" onClick={onClose} aria-label="Close tutorial">
          <X size={17} />
        </button>
        <p className="eyebrow">Step {step + 1} of {STEPS.length}</p>
        <h2 id="tour-title">{title}</h2>
        <p>{description}</p>
        <div className="tour-progress" aria-label={`Tutorial step ${step + 1} of ${STEPS.length}`}>
          {STEPS.map((item, index) => <span key={item[0]} className={index <= step ? "done" : ""} />)}
        </div>
        <div className="tour-actions">
          <button className="button ghost" type="button" onClick={onClose}>Skip</button>
          <div>
            <button className="button ghost" type="button" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>
              <ArrowLeft size={15} /> Back
            </button>
            <button
              className="button primary"
              type="button"
              onClick={() => step === STEPS.length - 1 ? onClose() : setStep((value) => value + 1)}
            >
              {step === STEPS.length - 1 ? "Finish" : "Next"} <ArrowRight size={15} />
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
