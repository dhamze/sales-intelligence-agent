"""Mapping CSV columns to fields, and turning raw rows into validated records (pure functions).

A mapping is {csv header: target}, where target is a field name, ATTRIBUTES (keep the value
in the company's `attributes`, so nothing is lost), or None (ignore the column).
"""

import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from sia.modules.companies.domains import InvalidDomainError, normalize_domain
from sia.modules.companies.schemas import MAX_ATTRIBUTES, CompanyCreate
from sia.modules.contacts.schemas import ContactCreate
from sia.modules.imports.parsing import ParsedCsv

ATTRIBUTES = "attributes"


class EntityType(StrEnum):
    COMPANIES = "companies"
    CONTACTS = "contacts"


# Target field -> header spellings recognised automatically (compared after normalisation).
_COMPANY_ALIASES: dict[str, list[str]] = {
    "name": ["name", "company", "company name", "account", "account name", "organization",
             "organisation", "organization name", "business name"],
    "domain": ["domain", "company domain", "website domain", "email domain"],
    "website": ["website", "url", "web", "homepage", "site", "company website", "company url",
                "website url"],
    "industry": ["industry", "sector", "vertical"],
    "employee_count": ["employees", "employee count", "number of employees", "headcount",
                       "no of employees", "staff", "company size", "employee size"],
    "country": ["country", "hq country", "country code", "headquarters country"],
    "city": ["city", "hq city", "headquarters city", "town"],
    "description": ["description", "about", "summary", "company description", "overview"],
}  # fmt: skip

_CONTACT_ALIASES: dict[str, list[str]] = {
    "first_name": ["first name", "firstname", "given name", "first", "forename"],
    "last_name": ["last name", "lastname", "surname", "family name", "last"],
    "full_name": ["name", "full name", "contact name", "contact", "person"],
    "email": ["email", "email address", "e mail", "work email", "mail", "business email"],
    "title": ["title", "job title", "position", "role", "job role"],
    "phone": ["phone", "phone number", "mobile", "telephone", "work phone", "mobile phone"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin profile", "linkedin profile url"],
    "company_domain": ["company domain", "domain", "website", "company website", "company url"],
}  # fmt: skip

FIELDS: dict[EntityType, list[str]] = {
    EntityType.COMPANIES: list(_COMPANY_ALIASES),
    EntityType.CONTACTS: list(_CONTACT_ALIASES),
}

# Shared mailbox providers: an email at gmail.com says nothing about the person's employer.
FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
        "msn.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.de",
        "gmx.net", "web.de", "yandex.ru", "mail.ru", "qq.com", "163.com", "zoho.com",
    }
)  # fmt: skip


def _normalise_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def detect_mapping(headers: list[str], entity: EntityType) -> dict[str, str | None]:
    aliases = _COMPANY_ALIASES if entity == EntityType.COMPANIES else _CONTACT_ALIASES
    lookup = {alias: target for target, names in aliases.items() for alias in names}
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for header in headers:
        target = lookup.get(_normalise_header(header))
        if target is not None and target not in used:
            mapping[header] = target
            used.add(target)
        else:
            mapping[header] = ATTRIBUTES if entity == EntityType.COMPANIES else None
    return mapping


class InvalidMappingError(ValueError):
    pass


def validate_mapping(
    mapping: dict[str, str | None], headers: list[str], entity: EntityType
) -> dict[str, str | None]:
    unknown_headers = set(mapping) - set(headers)
    if unknown_headers:
        raise InvalidMappingError(f"Unknown columns: {', '.join(sorted(unknown_headers))}")
    allowed = set(FIELDS[entity]) | ({ATTRIBUTES} if entity == EntityType.COMPANIES else set())
    targets = [t for t in mapping.values() if t is not None]
    invalid = set(targets) - allowed
    if invalid:
        raise InvalidMappingError(f"Unknown fields: {', '.join(sorted(invalid))}")
    repeated = {t for t in targets if t != ATTRIBUTES and targets.count(t) > 1}
    if repeated:
        raise InvalidMappingError(f"Mapped more than once: {', '.join(sorted(repeated))}")
    complete = {header: mapping.get(header) for header in headers}
    if entity == EntityType.COMPANIES and not {"name", "domain", "website"} & set(targets):
        raise InvalidMappingError("Map at least one of: name, domain, website.")
    if entity == EntityType.CONTACTS and not {
        "email",
        "first_name",
        "last_name",
        "full_name",
    } & set(targets):
        raise InvalidMappingError("Map at least one of: email, first_name, last_name, full_name.")
    return complete


@dataclass(frozen=True)
class RowError:
    row: int  # line number in the file
    field: str | None
    message: str


@dataclass
class PreparedRows:
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    duplicate_rows: int = 0
    invalid_rows: int = 0


# Whole numbers with thousands separators in any common style: 1,200 / 117.000 / 1 200 / 1'200.
_GROUPED_INT = re.compile(r"^\d{1,3}([,.\s'_])\d{3}(?:\1\d{3})*$")  # same separator throughout


def _parse_int(value: str) -> str:
    """Normalise thousands-grouped integers to plain digits ("117.000" -> "117000").

    Without this, "117.000" (European for 117 thousand) would be read as the decimal 117.0 and
    silently stored as 117. Anything that is not cleanly grouped (e.g. "12.5") is passed on
    unchanged, and validation rejects it as not a whole number.
    """
    compact = value.strip()
    if _GROUPED_INT.match(compact):
        return re.sub(r"\D", "", compact)
    return compact


def _errors_of(exc: ValidationError, line: int) -> list[RowError]:
    errors = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ()) if not isinstance(part, int)]
        message = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
        errors.append(RowError(row=line, field=loc[0] if loc else None, message=message))
    return errors


def _company_record(values: dict[str, str], extras: dict[str, str]) -> dict[str, Any]:
    if values.get("employee_count"):
        values["employee_count"] = _parse_int(values["employee_count"])
    if not values.get("name"):  # many lists only have a website or domain
        values["name"] = values.get("domain") or values.get("website") or ""
    attributes = {k: v for k, v in extras.items() if v}
    data: dict[str, Any] = {**values, "attributes": dict(list(attributes.items())[:MAX_ATTRIBUTES])}
    return CompanyCreate.model_validate(data).model_dump()


def _contact_record(values: dict[str, str]) -> dict[str, Any]:
    full_name = values.pop("full_name", "")
    if full_name and not values.get("first_name") and not values.get("last_name"):
        first, _, last = full_name.strip().rpartition(" ")
        values["first_name"], values["last_name"] = (first, last) if first else (last, "")
    company_domain = values.pop("company_domain", "")
    record = ContactCreate.model_validate(values).model_dump()
    record["company_domain"] = _company_domain(company_domain, record.get("email"))
    return record


def _company_domain(explicit: str, email: str | None) -> str | None:
    """Best effort: an explicit company domain, else the email's domain (unless webmail)."""
    for candidate in (explicit, (email or "").rpartition("@")[2]):
        if not candidate:
            continue
        try:
            domain = normalize_domain(candidate)
        except InvalidDomainError:
            continue
        if domain not in FREE_EMAIL_DOMAINS:
            return domain
    return None


def prepare_rows(
    parsed: ParsedCsv, mapping: dict[str, str | None], entity: EntityType
) -> PreparedRows:
    """Validate every row; drop invalid rows and in-file duplicates (first occurrence wins)."""
    result = PreparedRows()
    seen: dict[str, int] = {}
    dedupe_key = "domain" if entity == EntityType.COMPANIES else "email"
    for line, row in zip(parsed.row_numbers, parsed.rows, strict=True):
        values: dict[str, str] = {}
        extras: dict[str, str] = {}
        for header, cell in zip(parsed.headers, row, strict=True):
            target = mapping.get(header)
            if target == ATTRIBUTES:
                extras[header] = cell
            elif target is not None and cell:  # an empty cell means "not provided"
                values[target] = cell
        try:
            if entity == EntityType.COMPANIES:
                record = _company_record(values, extras)
            else:
                record = _contact_record(values)
        except ValidationError as exc:
            result.invalid_rows += 1
            result.errors.extend(_errors_of(exc, line))
            continue

        key = record.get(dedupe_key)
        if key:
            if key in seen:
                result.duplicate_rows += 1
                result.errors.append(
                    RowError(line, dedupe_key, f"Duplicate of line {seen[key]} in this file.")
                )
                continue
            seen[key] = line
        record["_line"] = line
        record["id"] = uuid.uuid4()
        result.records.append(record)
    return result
