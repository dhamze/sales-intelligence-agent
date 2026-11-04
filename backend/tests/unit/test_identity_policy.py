"""Exhaustive checks of the role rules (3 roles -> every combination is cheap to test)."""

import itertools

import pytest

from sia.modules.identity.models import Role
from sia.modules.identity.policy import can_change_role, can_remove_member, has_at_least

MEMBER, ADMIN, OWNER = Role.MEMBER, Role.ADMIN, Role.OWNER


@pytest.mark.parametrize(
    ("role", "minimum", "expected"),
    [
        (MEMBER, MEMBER, True),
        (MEMBER, ADMIN, False),
        (ADMIN, ADMIN, True),
        (ADMIN, OWNER, False),
        (OWNER, OWNER, True),
        (OWNER, MEMBER, True),
    ],
)
def test_role_hierarchy(role: Role, minimum: Role, expected: bool) -> None:
    assert has_at_least(role, minimum) is expected


@pytest.mark.parametrize(("target", "new"), list(itertools.product(Role, Role)))
def test_members_can_never_change_roles(target: Role, new: Role) -> None:
    assert not can_change_role(MEMBER, target, new)


@pytest.mark.parametrize(("target", "new"), list(itertools.product(Role, Role)))
def test_owners_can_make_any_role_change(target: Role, new: Role) -> None:
    assert can_change_role(OWNER, target, new)


@pytest.mark.parametrize(("target", "new"), list(itertools.product(Role, Role)))
def test_admins_cannot_grant_or_touch_owner_role(target: Role, new: Role) -> None:
    expected = OWNER not in (target, new)
    assert can_change_role(ADMIN, target, new) is expected


@pytest.mark.parametrize("role", list(Role))
def test_anyone_can_remove_themselves(role: Role) -> None:
    assert can_remove_member(role, role, is_self=True)


@pytest.mark.parametrize(
    ("actor", "target", "expected"),
    [
        (MEMBER, MEMBER, False),
        (MEMBER, ADMIN, False),
        (MEMBER, OWNER, False),
        (ADMIN, MEMBER, True),
        (ADMIN, ADMIN, True),
        (ADMIN, OWNER, False),
        (OWNER, MEMBER, True),
        (OWNER, ADMIN, True),
        (OWNER, OWNER, True),
    ],
)
def test_removing_others(actor: Role, target: Role, expected: bool) -> None:
    assert can_remove_member(actor, target, is_self=False) is expected
