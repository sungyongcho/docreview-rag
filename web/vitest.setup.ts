import "@testing-library/jest-dom/vitest";

// Tests must not inherit the developer shell's bundle mode: default to the
// public build and let individual tests stub the mode they exercise.
process.env.NEXT_PUBLIC_ADMIN_MODE = "canned";

// jsdom does not implement native dialog opening/closing. Keep that limitation in
// the test environment rather than adding a non-modal production fallback.
if (typeof HTMLDialogElement !== "undefined") {
  Object.assign(HTMLDialogElement.prototype, {
    showModal(this: HTMLDialogElement) { this.open = true; },
    close(this: HTMLDialogElement) { this.open = false; },
  });
}
