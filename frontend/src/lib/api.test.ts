import { afterEach, describe, expect, it, vi } from "vitest";

import { request } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("API request contract", () => {
  it("returns parsed JSON for a successful response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { value: 1 } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/api/health")).resolves.toEqual({
      success: true,
      data: { value: 1 },
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("rejects non-success responses instead of treating them as data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("denied", { status: 403, statusText: "Forbidden" })),
    );

    await expect(request("/api/admin")).rejects.toThrow("API error: 403 Forbidden");
  });
});
