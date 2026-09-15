"use client";

import { localizedDocumentationRoute } from "@/lib/documentation-registry.mjs";
import {
  anchorTarget,
  captureReadingState,
  cancelReadingState,
  consumeReadingState,
  documentRoot,
  openDetailAncestors,
  openDetails,
  latestReadingState,
  linkedQuickStartMode,
  quickStartMode,
  readingLine,
  rememberReadingState,
  routeDocumentId,
  routerPath,
  sectionScrollTop,
  withQuery,
} from "@/lib/documentation-reading";
import { LanguageSwitch, useI18n, type Locale } from "@/lib/i18n";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useLayoutEffect, type ReactNode } from "react";

/** Build the router-ready localized route for the current document, query included. */
function localizedDestination(pathname: string | null, locale: Locale, hash: string): string | null {
  const route = localizedDocumentationRoute(pathname || window.location.pathname, locale, hash);
  return route ? withQuery(routerPath(route), window.location.search) : null;
}

/** Language toggle for document pages: replaces the localized route instead of reloading it. */
export function DocumentationLanguageSwitch({ locale }: { locale: Locale }) {
  const router = useRouter();
  const pathname = usePathname();
  const { setLocale } = useI18n();

  // Only this document's other rendering is worth prefetching, not the whole manual.
  useEffect(() => {
    const route = localizedDocumentationRoute(pathname || window.location.pathname, locale === "en" ? "ko" : "en");
    if (route) router.prefetch(routerPath(route));
  }, [pathname, locale, router]);

  function choose(next: Locale) {
    const previous = latestReadingState();
    if (next === locale && !previous) return;
    if (next === locale) {
      cancelReadingState();
      const destination = localizedDestination(pathname, next, window.location.hash);
      if (destination) router.replace(destination, { scroll: false });
      return;
    }
    const captured = captureReadingState();
    const hash = captured.path.at(-1) ? `#${captured.path.at(-1)}` : window.location.hash;
    const destination = localizedDestination(pathname, next, hash);
    if (!destination) {
      setLocale(next);
      return;
    }
    const here = routerPath(window.location.pathname + window.location.search + window.location.hash);
    if (destination === here) return;
    const target = routeDocumentId(destination) ?? documentRoot()?.dataset.documentId;
    if (target) rememberReadingState({ ...captured, documentId: target, targetLocale: next });
    router.replace(destination, { scroll: false });
  }

  return <LanguageSwitch locale={locale} onChange={choose} />;
}

/**
 * Restores the captured reading position once a localized route commits and keeps the
 * shared locale preference aligned with the committed document, including popstate.
 */
export function DocumentationReadingBoundary({ documentId, locale, children }: { documentId: string; locale: Locale; children: ReactNode }) {
  const { locale: shared, setLocale } = useI18n();

  useLayoutEffect(() => {
    // Native anchoring cannot reach a target that was closed or hidden when it ran.
    function reachAnchor() {
      const anchor = anchorTarget(window.location.hash);
      if (!anchor) return;
      const opened = openDetailAncestors(anchor) > 0;
      const stranded = window.scrollY === 0 && anchor.getBoundingClientRect().top > readingLine();
      if (opened || stranded) {
        window.scrollTo(0, Math.max(0, anchor.getBoundingClientRect().top + window.scrollY - readingLine()));
      }
    }
    function restore() {
      const intent = latestReadingState();
      const mode = linkedQuickStartMode() ?? (intent?.documentId === documentId ? intent.quickstart : undefined);
      const renderedMode = quickStartMode();
      if (mode && renderedMode && mode !== renderedMode) return;
      const pending = consumeReadingState(documentId, locale);
      if (pending) {
        openDetails(pending.details);
        const anchor = anchorTarget(window.location.hash);
        if (anchor) openDetailAncestors(anchor);
        const top = sectionScrollTop(pending);
        if (top !== null) window.scrollTo(0, top);
      } else {
        reachAnchor();
      }
      documentRoot()?.setAttribute("data-document-ready", locale);
    }
    restore();
    window.addEventListener("hashchange", restore);
    window.addEventListener("docreview:quickstart-ready", restore);
    return () => {
      window.removeEventListener("hashchange", restore);
      window.removeEventListener("docreview:quickstart-ready", restore);
    };
  }, [documentId, locale]);

  useLayoutEffect(() => {
    if (shared !== locale) setLocale(locale);
  }, [shared, locale, setLocale]);

  return <>{children}</>;
}
