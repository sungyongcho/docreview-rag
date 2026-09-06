/**
 * Build-time facts about which bundle this is.
 *
 * `NEXT_PUBLIC_ADMIN_MODE` is inlined by the compiler, so a guard written against this
 * constant lets the minifier drop the branch entirely. That is what keeps the local
 * engine's vocabulary out of a public bundle rather than merely hiding it. The runtime
 * hostname check in `deployment.ts` cannot do that: it would hide the controls while
 * still shipping every string.
 */
export const LOCAL_ENGINE_VISIBLE = process.env.NEXT_PUBLIC_ADMIN_MODE === "live";
