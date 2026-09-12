import "@testing-library/jest-dom/vitest";

// Tests must not inherit the developer shell's bundle mode: default to the
// public build and let individual tests stub the mode they exercise.
process.env.NEXT_PUBLIC_ADMIN_MODE = "canned";
