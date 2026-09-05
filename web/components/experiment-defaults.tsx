"use client";
import { useI18n } from "@/lib/i18n";


import { useEffect, useState } from "react";
import { getAdminSnapshots, getGoldenRevisions, getGoldenSuites } from "@/lib/api";
import { useNotifications } from "@/components/notifications";
import { loadDefaultProfile, loadExperimentDefaults, resetDefaultProfile, resetExperimentDefaults, saveDefaultProfile, saveExperimentDefaults } from "@/lib/storage";
import { DEFAULT_EXPERIMENT_DEFAULTS } from "@/lib/types";
import type { ExperimentDefaults, GoldenRevision, GoldenSuite, PublishedSnapshot, RetrievalProfile, SuiteId } from "@/lib/types";

/** Edit saved experiment defaults inside Measure without opening Settings. */
export function ExperimentDefaultsForm({ profile, onSaved }: { profile: RetrievalProfile; onSaved?: (defaults: ExperimentDefaults) => void }) {
  const { t, locale } = useI18n();
  const { notify } = useNotifications();
  const [experimentDefaults, setExperimentDefaults] = useState(loadExperimentDefaults);
  const [suites, setSuites] = useState<GoldenSuite[]>([]);
  useEffect(() => { void getGoldenSuites().then((rows) => setSuites(Array.isArray(rows) ? rows : [])).catch((reason) => notify(String(reason), "error", "defaults-suites")); }, [notify]);
  const [experimentSnapshots, setExperimentSnapshots] = useState<PublishedSnapshot[]>([]);
  const [experimentRevisions, setExperimentRevisions] = useState<GoldenRevision[]>([]);
  useEffect(() => { void getAdminSnapshots().then(setExperimentSnapshots).catch((reason) => notify(String(reason), "error", "defaults-snapshots")); }, [notify]);
  useEffect(() => { void getGoldenRevisions(experimentDefaults.suite_id).then(setExperimentRevisions).catch((reason) => notify(String(reason), "error", "defaults-revisions")); }, [experimentDefaults.suite_id, notify]);
  function patchExperiment(update: Partial<ExperimentDefaults>) { setExperimentDefaults((current) => ({ ...current, ...update })); }
  function persistExperimentDefaults() {
    saveExperimentDefaults(experimentDefaults);
    saveDefaultProfile({ ...loadDefaultProfile(), retrieval_preset: experimentDefaults.retrieval_preset, custom_retrieval: experimentDefaults.retrieval_preset === "custom" ? profile : null });
    onSaved?.(experimentDefaults);
    notify(t("Experiment and new-conversation retrieval defaults saved."), "success", "experiment-defaults");
  }
  return <section className="surface" data-help="measure.defaults.form"><h2>{t("Experiment defaults")}</h2><div className="settings-form"><label>{t("Default golden suite")}<select value={experimentDefaults.suite_id} onChange={(event) => patchExperiment({ suite_id: event.target.value as SuiteId, golden_revision_id: null })}>{suites.map((suite) => <option key={suite.suite_id} value={suite.suite_id}>{suite.label}</option>)}</select></label><label>{t("Default golden revision")}<select value={experimentDefaults.golden_revision_id ?? ""} onChange={(event) => patchExperiment({ golden_revision_id: Number(event.target.value) || null })}><option value="">{t("Canonical JSON")}</option>{experimentRevisions.map((revision) => <option key={revision.revision_id} value={revision.revision_id}>{t("v")}{revision.version} · {t(revision.status)}</option>)}</select></label><label>{t("Default run mode")}<select value={experimentDefaults.mode} onChange={(event) => patchExperiment({ mode: event.target.value as ExperimentDefaults["mode"] })}><option value="quick">{t("Quick · current index")}</option><option value="matrix">{t("Matrix · isolated corpus")}</option></select></label><label>{t("Default ready snapshot")}<select value={experimentDefaults.snapshot_id ?? ""} onChange={(event) => patchExperiment({ snapshot_id: Number(event.target.value) || null })}><option value="">{t("None")}</option>{experimentSnapshots.filter((snapshot) => snapshot.status === "ready").map((snapshot) => <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>#{snapshot.snapshot_id} · {snapshot.label}</option>)}</select></label><label>{t("Comparison baseline")}<select value={experimentDefaults.baseline_snapshot_id ?? ""} onChange={(event) => patchExperiment({ baseline_snapshot_id: Number(event.target.value) || null })}><option value="">{t("None")}</option>{experimentSnapshots.filter((snapshot) => snapshot.status === "ready").map((snapshot) => <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>#{snapshot.snapshot_id} · {snapshot.label}</option>)}</select></label><label>{t("New conversation retrieval preset")}<select value={experimentDefaults.retrieval_preset} onChange={(event) => patchExperiment({ retrieval_preset: event.target.value as ExperimentDefaults["retrieval_preset"] })}><option value="balanced">{t("Balanced")}</option><option value="korean">{t("Korean")}</option><option value="accuracy">{t("Accuracy")}</option><option value="custom">{t("Current custom profile")}</option></select></label><p className="helper">{t("Saving defaults does not run a provider, index build, or evaluation. Build and Measure apply them the next time they open.")}</p><div className="action-row"><button className="button primary" type="button" onClick={persistExperimentDefaults}>{t("Save experiment defaults")}</button><button className="button" type="button" onClick={() => { if (window.confirm(t("Reset experiment defaults?"))) { resetExperimentDefaults(); setExperimentDefaults(DEFAULT_EXPERIMENT_DEFAULTS); notify(t("Experiment defaults reset."), "success", "experiment-defaults"); } }}>{t("Reset experiment defaults")}</button><button className="button" type="button" onClick={() => { if (window.confirm(t("Reset new conversation defaults?"))) { resetDefaultProfile(); notify(t("New conversation defaults reset."), "success", "profile-defaults"); } }}>{t("Reset new conversation defaults")}</button></div></div></section>;
}
