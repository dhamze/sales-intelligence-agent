"""Authorization rules for organisation roles, as pure functions (easy to test exhaustively).

    member < admin < owner

- Admins and owners manage the organisation and its members.
- Only owners can grant the owner role or change/remove an existing owner.
- Anyone can remove themselves (leave). The "at least one owner" rule needs database state,
  so the service enforces it.
"""

from sia.modules.identity.models import Role

_RANK = {Role.MEMBER: 0, Role.ADMIN: 1, Role.OWNER: 2}


def has_at_least(role: Role, minimum: Role) -> bool:
    return _RANK[role] >= _RANK[minimum]


def can_change_role(actor: Role, target_current: Role, new_role: Role) -> bool:
    if not has_at_least(actor, Role.ADMIN):
        return False
    touches_owner = Role.OWNER in (target_current, new_role)
    return actor == Role.OWNER or not touches_owner


def can_remove_member(actor: Role, target: Role, *, is_self: bool) -> bool:
    if is_self:
        return True
    if not has_at_least(actor, Role.ADMIN):
        return False
    return actor == Role.OWNER or target != Role.OWNER
