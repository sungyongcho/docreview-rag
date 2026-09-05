import { HELP_TOPICS, HELP_SCREEN_TITLES, type HelpScreen, type HelpTopic } from "./help-content";
import { translate, type Locale } from "./i18n";

export interface HelpSearchEntry { screen: HelpScreen; topic: HelpTopic; index: number }

export const HELP_ENTRIES: HelpSearchEntry[] = Object.entries(HELP_TOPICS).flatMap(([screen, topics]) => topics.map((topic, index) => ({ screen: screen as HelpScreen, topic, index })));

/** Match Korean or English queries locally, preferring titles over explanatory prose. */
export function searchHelp(query: string, locale: Locale, entries = HELP_ENTRIES): HelpSearchEntry[] {
  const normalize = (text: string) => text.normalize("NFKC").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const needle = normalize(query);
  const languages: Locale[] = [locale, locale === "ko" ? "en" : "ko"];
  if (!needle) return entries;
  const terms = needle.split(/\s+/);
  return entries.map((entry, order) => {
    const { topic } = entry;
    const title = normalize([topic.title, ...languages.map((language) => translate(language, topic.title))].join(" "));
    const prose = normalize([topic.id, HELP_SCREEN_TITLES[entry.screen], ...topic.body, topic.tune ?? "", ...languages.flatMap((language) => [...topic.body.map((paragraph) => translate(language, paragraph)), translate(language, topic.tune ?? "")])].join(" "));
    if (!terms.every((term) => title.includes(term) || prose.includes(term))) return { entry, score: 0, order };
    const score = (title.includes(needle) ? 30 : 0) + terms.reduce((sum, term) => sum + (title.includes(term) ? 12 : 2), 0);
    return { entry, score, order };
  }).filter(({ score }) => score > 0).sort((a, b) => b.score - a.score || a.order - b.order).map(({ entry }) => entry);
}

export function helpTopicScreen(id: string): HelpScreen | null {
  return HELP_ENTRIES.find((entry) => entry.topic.id === id)?.screen ?? null;
}

export function helpDestinationScreen(id: string): HelpScreen | null {
  if (id === "review.snapshot") return "measure.snapshots";
  if (id === "measure.snapshots.freeze") return "measure.runs";
  return helpTopicScreen(id);
}
