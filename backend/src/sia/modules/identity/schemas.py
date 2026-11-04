"""Request and response models for the identity API."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from sia.modules.identity.models import EMAIL_MAX_LENGTH, NAME_MAX_LENGTH, Role

# NIST SP 800-63B: length matters, composition rules don't. The maximum stops attackers from
# submitting megabyte-long "passwords" to tie up the (deliberately slow) hasher.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


NameStr = Annotated[str, Field(min_length=1, max_length=NAME_MAX_LENGTH)]


class SignupRequest(_Request):
    email: EmailStr = Field(max_length=EMAIL_MAX_LENGTH)
    password: SecretStr = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    name: NameStr
    organization_name: NameStr


class LoginRequest(_Request):
    # Deliberately loose: any malformed input simply fails as "invalid credentials".
    email: str = Field(min_length=1, max_length=EMAIL_MAX_LENGTH)
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class SwitchOrganizationRequest(_Request):
    organization_id: uuid.UUID


class UpdateOrganizationRequest(_Request):
    name: NameStr


class UpdateMemberRequest(_Request):
    role: Role


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str


class MembershipOut(BaseModel):
    organization: OrganizationOut
    role: Role


class MeResponse(BaseModel):
    user: UserOut
    active_organization: OrganizationOut | None
    role: Role | None
    memberships: list[MembershipOut]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: Role
    joined_at: datetime
