import { describe, expect, it } from "vitest";

import { ApiError, unwrap } from "./client";

describe("ApiError", () => {
  it("reads the backend's standard error shape", () => {
    const error = new ApiError(409, {
      error: { code: "domain_taken", message: "Already exists.", request_id: "abc123" },
    });

    expect(error.status).toBe(409);
    expect(error.code).toBe("domain_taken");
    expect(error.message).toBe("Already exists.");
    expect(error.requestId).toBe("abc123");
  });

  it("maps validation details to field errors", () => {
    const error = new ApiError(422, {
      error: {
        code: "validation_error",
        message: "Request validation failed.",
        details: [
          { loc: ["body", "email"], msg: "value is not a valid email address", type: "x" },
          { loc: ["body", "attributes", 0], msg: "Value error, Too many.", type: "y" },
          { msg: "no location" },
        ],
      },
    });

    expect(error.fieldErrors).toEqual([
      { field: "email", message: "value is not a valid email address" },
      { field: "attributes", message: "Too many." },
    ]);
  });

  it("tolerates unexpected bodies (e.g. a proxy's HTML error page)", () => {
    const error = new ApiError(502, "<html>Bad Gateway</html>");

    expect(error.code).toBe("unknown_error");
    expect(error.message).toBe("Something went wrong.");
    expect(error.fieldErrors).toEqual([]);
  });
});

describe("unwrap", () => {
  it("returns data for successful responses", async () => {
    const data = await unwrap(Promise.resolve({ data: { ok: true }, response: new Response() }));

    expect(data).toEqual({ ok: true });
  });

  it("throws ApiError for error responses", async () => {
    const call = Promise.resolve({
      error: { error: { code: "not_found", message: "Company not found." } },
      response: new Response(null, { status: 404 }),
    });

    await expect(unwrap(call)).rejects.toMatchObject({ status: 404, code: "not_found" });
  });

  it("turns network failures into a readable error", async () => {
    await expect(unwrap(Promise.reject(new TypeError("Failed to fetch")))).rejects.toMatchObject({
      code: "network_error",
    });
  });
});
