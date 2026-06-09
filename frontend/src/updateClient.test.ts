import { describe, expect, it } from "vitest";
import { createTauriUpdateApi } from "./updateClient";

describe("createTauriUpdateApi", () => {
  it("uses the package version in browser preview", async () => {
    const api = createTauriUpdateApi();

    await expect(api.getVersion()).resolves.toBe("1.2.1");
  });
});
