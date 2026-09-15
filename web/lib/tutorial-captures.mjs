const CAPTURE_PATH = /^assets\/captures\/[a-z0-9-]+\.(?:ko|en)\.(?:(?:full|mobile|mobile-full|mobile-detail|mobile-detail-full|detail|detail-full|detail-mobile|detail-mobile-full)\.)?png$/;

/** Validate capture instructions without requiring images that have not been shot yet. */
export function validateCapturePlan(plan, documents = new Map()) {
  if (plan.version !== 1 || plan.theme !== "light" || plan.localOnly !== true || plan.locales?.join(",") !== "ko,en" || !Array.isArray(plan.scenes)) throw new Error("Invalid tutorial capture plan");
  const ids = new Set();
  for (const scene of plan.scenes) {
    if (!/^[a-z][a-z0-9-]*$/.test(scene.id) || ids.has(scene.id)) throw new Error(`Invalid or duplicate capture ID: ${scene.id}`);
    ids.add(scene.id);
    if (!["pending", "accepted"].includes(scene.status) || !["dev", "prod"].includes(scene.mode) || !scene.route?.startsWith("/docreview-rag/") || !scene.state?.trim() || !scene.cropTarget?.trim()) throw new Error(`Incomplete capture state: ${scene.id}`);
    if (!scene.callouts?.length || scene.callouts.some((callout, index) => callout.number !== index + 1 || !callout.target?.trim() || !callout.label?.ko?.trim() || !callout.label?.en?.trim())) throw new Error(`Invalid capture callouts: ${scene.id}`);
    for (const locale of plan.locales) {
      const variant = scene.variants?.[locale];
      if (!variant?.alt?.trim() || !variant.caption?.trim()) throw new Error(`Missing capture translation: ${scene.id}/${locale}`);
      if (scene.mobileDetail && (!scene.mobile || !variant.mobileDetailAlt?.trim() || !variant.mobileDetailCaption?.trim())) throw new Error(`Missing mobile detail translation: ${scene.id}/${locale}`);
      if (scene.detail && (!variant.detailAlt?.trim() || !variant.detailCaption?.trim())) throw new Error(`Missing detail translation: ${scene.id}/${locale}`);
      for (const path of [variant.original, variant.focused, ...(scene.mobile ? [variant.mobile] : []), ...(scene.mobileDetail ? [variant.mobileDetail, variant.mobileDetailOriginal] : []),
        ...(scene.detail ? [variant.detailFocused, variant.detailOriginal, ...(scene.mobile ? [variant.detailMobile, variant.detailMobileOriginal] : [])] : [])]) {
        if (!CAPTURE_PATH.test(path ?? "") || !path.includes(`.${locale}.`)) throw new Error(`Invalid capture asset: ${scene.id}/${locale}`);
      }
      if (!scene.references?.some((reference) => reference.file.startsWith(`${locale}/`))) throw new Error(`Missing capture placement: ${scene.id}/${locale}`);
    }
    if (scene.status === "accepted") {
      const box = (callout, locale, kind) => {
        const value = callout.bounds?.[locale]?.[kind];
        return value && [value.x, value.y, value.w, value.h].every((v) => Number.isFinite(v) && v >= 0) && value.w > 0 && value.h > 0 ? value : null;
      };
      // A scene can publish a main figure and a supplemental one. Each figure carries only the callouts it
      // actually contains, so a marker is never drawn over a target that lives in the other figure.
      const wide = ["focused", ...(scene.detail ? ["detail"] : [])];
      const narrow = scene.mobile ? ["mobile", ...(scene.mobileDetail ? ["mobileDetail"] : []), ...(scene.detail ? ["detailMobile"] : [])] : [];
      const frames = [...wide, ...narrow];
      const used = new Set();
      for (const callout of scene.callouts) {
        for (const locale of plan.locales) {
          for (const frame of frames) {
            if (callout.bounds?.[locale]?.[frame] && !box(callout, locale, frame)) throw new Error(`Invalid accepted capture bounds: ${scene.id}/${locale}/${frame}#${callout.number}`);
            if (box(callout, locale, frame)) used.add(frame);
          }
          if (!wide.some((frame) => box(callout, locale, frame))) throw new Error(`Missing accepted capture bounds: ${scene.id}/${locale}/focused#${callout.number}`);
          if (narrow.length && !narrow.some((frame) => box(callout, locale, frame))) throw new Error(`Missing accepted capture bounds: ${scene.id}/${locale}/mobile#${callout.number}`);
        }
      }
      for (const frame of frames) if (!used.has(frame)) throw new Error(`Unused capture frame: ${scene.id}/${frame}`);
    }
  }
  for (const [file, document] of documents) {
    for (const id of document.captures ?? []) {
      const scene = plan.scenes.find((entry) => entry.id === id);
      if (!scene || !scene.references.some((reference) => reference.file === file)) throw new Error(`Unknown capture placement: ${file}#${id}`);
    }
  }
  if (documents.size) {
    for (const scene of plan.scenes) {
      for (const reference of scene.references) {
        const document = documents.get(reference.file);
        if (!document?.captures?.includes(scene.id)) throw new Error(`Missing capture marker: ${reference.file}#${scene.id}`);
        if (reference.section && !document.headings?.some((heading) => heading.id === reference.section)) throw new Error(`Missing capture section: ${reference.file}#${reference.section}`);
      }
    }
  }
  return plan;
}

function captureAssetUrl(path, revision) {
  return path ? `/docreview-rag/tutorial-assets/${path.slice(7)}${revision ? `?v=${encodeURIComponent(revision)}` : ""}` : undefined;
}

/** Only reviewed captures may add an original-image link to the published page. */
export function captureOriginal(plan, id, locale, revision) {
  const scene = plan.scenes.find((entry) => entry.id === id && entry.status === "accepted");
  return captureAssetUrl(scene?.variants?.[locale]?.original, revision);
}

/** Numbered callout overlays for an accepted scene, localized and kept in image pixels. */
export function captureCallouts(plan, id, locale) {
  const scene = plan.scenes.find((entry) => entry.id === id && entry.status === "accepted");
  if (!scene) return undefined;
  return scene.callouts.map((callout) => ({
    number: callout.number,
    label: callout.label[locale],
    bounds: callout.bounds?.[locale]?.focused,
    mobileBounds: callout.bounds?.[locale]?.mobile,
  }));
}

/** Mobile variant of an accepted scene, with its plan path for intrinsic-size lookup. */
export function captureMobile(plan, id, locale, revision) {
  const scene = plan.scenes.find((entry) => entry.id === id && entry.status === "accepted" && entry.mobile);
  const path = scene?.variants?.[locale]?.mobile;
  return path ? { src: captureAssetUrl(path, revision), path } : undefined;
}

/** Supplemental figure shown at every width, for readiness the main crop's surface does not carry. */
export function captureDetail(plan, id, locale, revision) {
  const scene = plan.scenes.find((entry) => entry.id === id && entry.status === "accepted" && entry.detail);
  const variant = scene?.variants?.[locale];
  if (!variant?.detailFocused) return undefined;
  return {
    path: variant.detailFocused,
    src: captureAssetUrl(variant.detailFocused, revision),
    originalSrc: captureAssetUrl(variant.detailOriginal, revision),
    mobilePath: variant.detailMobile,
    mobileSrc: captureAssetUrl(variant.detailMobile, revision),
    alt: variant.detailAlt,
    caption: variant.detailCaption,
    callouts: scene.callouts.filter((callout) => callout.bounds?.[locale]?.detail).map((callout) => ({
      number: callout.number,
      label: callout.label[locale],
      bounds: callout.bounds[locale].detail,
      mobileBounds: callout.bounds[locale].detailMobile,
    })),
  };
}

/** Supplemental mobile-only figure for content the narrow main crop cannot hold, with its own crop, callouts and original. */
export function captureMobileDetail(plan, id, locale, revision) {
  const scene = plan.scenes.find((entry) => entry.id === id && entry.status === "accepted" && entry.mobileDetail);
  const variant = scene?.variants?.[locale];
  if (!variant?.mobileDetail) return undefined;
  return {
    path: variant.mobileDetail,
    src: captureAssetUrl(variant.mobileDetail, revision),
    originalSrc: captureAssetUrl(variant.mobileDetailOriginal, revision),
    alt: variant.mobileDetailAlt,
    caption: variant.mobileDetailCaption,
    callouts: scene.callouts.filter((callout) => callout.bounds?.[locale]?.mobileDetail).map((callout) => ({ number: callout.number, label: callout.label[locale], bounds: callout.bounds[locale].mobileDetail })),
  };
}
