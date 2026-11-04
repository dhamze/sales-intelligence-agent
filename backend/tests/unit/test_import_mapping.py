import pytest

from sia.modules.imports.mapping import (
    ATTRIBUTES,
    EntityType,
    InvalidMappingError,
    PreparedRows,
    detect_mapping,
    prepare_rows,
    validate_mapping,
)
from sia.modules.imports.parsing import parse_csv

COMPANIES, CONTACTS = EntityType.COMPANIES, EntityType.CONTACTS


def test_company_columns_are_detected_from_common_spellings() -> None:
    headers = ["Company Name", "Website URL", "No. of Employees", "HQ Country", "CRM ID"]

    assert detect_mapping(headers, COMPANIES) == {
        "Company Name": "name",
        "Website URL": "website",
        "No. of Employees": "employee_count",
        "HQ Country": "country",
        "CRM ID": ATTRIBUTES,  # unknown columns are kept, not dropped
    }


def test_contact_columns_are_detected_and_unknown_ones_ignored() -> None:
    headers = ["First Name", "Surname", "E-mail", "Job Title", "Favourite colour"]

    assert detect_mapping(headers, CONTACTS) == {
        "First Name": "first_name",
        "Surname": "last_name",
        "E-mail": "email",
        "Job Title": "title",
        "Favourite colour": None,
    }


def test_a_field_is_auto_mapped_only_once() -> None:
    mapping = detect_mapping(["Website", "URL"], COMPANIES)

    assert mapping == {"Website": "website", "URL": ATTRIBUTES}


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ({"Nope": "name"}, "Unknown columns"),
        ({"A": "password_hash"}, "Unknown fields"),
        ({"A": "name", "B": "name"}, "more than once"),
        ({"A": "industry", "B": ATTRIBUTES}, "at least one of"),
    ],
)
def test_invalid_mappings(mapping: dict[str, str | None], message: str) -> None:
    with pytest.raises(InvalidMappingError, match=message):
        validate_mapping(mapping, ["A", "B"], COMPANIES)


def _prepare(csv: str, entity: EntityType) -> PreparedRows:
    parsed = parse_csv(csv.encode())
    return prepare_rows(parsed, detect_mapping(parsed.headers, entity), entity)


def test_company_rows_are_normalised() -> None:
    result = _prepare(
        "Company,Website,Employees,Tier,Notes\n"
        'Acme,https://www.acme.com/about,"1,200",Gold,\n'
        ",globex.com,12,,\n",  # no name: falls back to the domain
        COMPANIES,
    )

    acme, globex = result.records
    assert (acme["name"], acme["domain"], acme["employee_count"]) == ("Acme", "acme.com", 1200)
    assert acme["attributes"] == {"Tier": "Gold"}  # blank extras are not stored
    assert (globex["name"], globex["domain"]) == ("globex.com", "globex.com")
    assert result.errors == []


def test_invalid_rows_are_reported_with_line_and_field_and_skipped() -> None:
    result = _prepare(
        "Company,Website,Employees\nAcme,acme.com,ten\nGlobex,localhost,5\nInitech,initech.com,3\n",
        COMPANIES,
    )

    assert [r["name"] for r in result.records] == ["Initech"]
    assert result.invalid_rows == 2
    assert {(e.row, e.field) for e in result.errors} == {(2, "employee_count"), (3, "website")}


def test_duplicates_within_the_file_are_detected_in_any_form() -> None:
    result = _prepare(
        "Company,Website\nAcme,acme.com\nAcme Inc,https://WWW.ACME.COM\nGlobex,globex.com\n",
        COMPANIES,
    )

    assert [r["name"] for r in result.records] == ["Acme", "Globex"]  # first occurrence wins
    assert result.duplicate_rows == 1
    assert result.errors[0].message == "Duplicate of line 2 in this file."


def test_contact_rows_split_names_and_find_company_domain() -> None:
    result = _prepare(
        "Name,Email,Company Website\n"
        "Peter Gibbons,Peter@Initech.com,\n"
        "Bob Slydell,bob@gmail.com,\n"  # webmail domain says nothing about the employer
        "Michael Bolton,mb@consultant.example.com,https://www.initech.com\n",
        CONTACTS,
    )

    peter, bob, michael = result.records
    assert (peter["first_name"], peter["last_name"]) == ("Peter", "Gibbons")
    assert (peter["email"], peter["company_domain"]) == ("peter@initech.com", "initech.com")
    assert bob["company_domain"] is None
    assert michael["company_domain"] == "initech.com"  # explicit column beats email domain


def test_contact_without_email_or_name_is_invalid() -> None:
    result = _prepare("Email,Title\n,CEO\nann@acme.com,CTO\n", CONTACTS)

    assert [r["email"] for r in result.records] == ["ann@acme.com"]
    assert result.invalid_rows == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1200", 1200),
        ("1,200", 1200),
        ("117.000", 117000),  # European grouping: must NOT become 117
        ("1 200 000", 1200000),
        ("1'200", 1200),  # Swiss
        ("1_200", 1200),
    ],
)
def test_employee_counts_with_thousands_separators(raw: str, expected: int) -> None:
    result = _prepare(f'Company,Website,Employees\nAcme,acme.com,"{raw}"\n', COMPANIES)

    assert result.records[0]["employee_count"] == expected


@pytest.mark.parametrize("raw", ["12.5", "1,2", "1.200,5", "1,200.000", "ten", "-5"])
def test_ambiguous_or_fractional_employee_counts_are_rejected(raw: str) -> None:
    result = _prepare(f'Company,Website,Employees\nAcme,acme.com,"{raw}"\n', COMPANIES)

    assert result.records == []
    assert result.errors[0].field == "employee_count"
