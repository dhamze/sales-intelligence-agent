/**
 * Which member-management controls to show. Mirrors the backend's rules (sia/modules/identity/
 * policy.py) so people only see actions they can take; the server still enforces every rule.
 */
import type { Role } from "@/features/auth/api";

const RANK: Record<Role, number> = { member: 0, admin: 1, owner: 2 };

/** Roles `actor` may assign to someone who currently has `target`. */
export function assignableRoles(actor: Role, target: Role): Role[] {
  if (RANK[actor] < RANK.admin) return [];
  if (actor === "owner") return ["member", "admin", "owner"];
  return target === "owner" ? [] : ["member", "admin"];
}

export function canRemove(actor: Role, target: Role, isSelf: boolean): boolean {
  if (isSelf) return true;
  if (RANK[actor] < RANK.admin) return false;
  return actor === "owner" || target !== "owner";
}
