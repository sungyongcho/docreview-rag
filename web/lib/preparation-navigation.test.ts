import { expect, it } from "vitest";
import { preparationErrorTarget } from "./preparation-navigation";

it("routes only typed source absence to acquisition", () => {
  expect(preparationErrorTarget("source_missing")).toBe(1);
  expect(preparationErrorTarget("sourcemissingerror")).toBe(1);
  expect(preparationErrorTarget("source_invalid")).toBe("setup");
  expect(preparationErrorTarget("worker_error")).toBe("setup");
});
