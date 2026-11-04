import { describe, expect, it } from "vitest";

import { assignableRoles, canRemove } from "./policy";

// Same expectations as the backend's exhaustive policy tests (test_identity_policy.py).
describe("assignableRoles", () => {
  it.each([
    ["member", "member", []],
    ["member", "owner", []],
    ["admin", "member", ["member", "admin"]],
    ["admin", "admin", ["member", "admin"]],
    ["admin", "owner", []],
    ["owner", "member", ["member", "admin", "owner"]],
    ["owner", "owner", ["member", "admin", "owner"]],
  ] as const)("%s acting on %s may assign %j", (actor, target, expected) => {
    expect(assignableRoles(actor, target)).toEqual(expected);
  });
});

describe("canRemove", () => {
  it.each([
    ["member", "member", false],
    ["admin", "member", true],
    ["admin", "admin", true],
    ["admin", "owner", false],
    ["owner", "owner", true],
  ] as const)("%s removing %s -> %s", (actor, target, expected) => {
    expect(canRemove(actor, target, false)).toBe(expected);
  });

  it("anyone may leave", () => {
    expect(canRemove("member", "member", true)).toBe(true);
  });
});
