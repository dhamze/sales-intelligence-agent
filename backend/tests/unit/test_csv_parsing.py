import pytest

from sia.modules.imports.parsing import (
    MAX_COLUMNS,
    MAX_ROWS,
    ImportFileError,
    parse_csv,
)


def test_comma_separated_utf8_with_excel_byte_order_mark() -> None:
    parsed = parse_csv("﻿Name,Website\nAcme,acme.com\n".encode())

    assert parsed.headers == ["Name", "Website"]  # BOM not glued onto the first header
    assert parsed.rows == [["Acme", "acme.com"]]
    assert (parsed.encoding, parsed.delimiter) == ("utf-8", ",")


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_other_separators_are_detected(delimiter: str) -> None:
    content = f"Name{delimiter}City\nAcme{delimiter}Berlin\nGlobex{delimiter}Paris\n"

    parsed = parse_csv(content.encode())

    assert parsed.delimiter == delimiter
    assert parsed.rows == [["Acme", "Berlin"], ["Globex", "Paris"]]


def test_windows_1252_fallback() -> None:
    parsed = parse_csv("Name;City\nSociété Générale;Paris\n".encode("cp1252"))

    assert parsed.encoding == "windows-1252"
    assert parsed.rows[0][0] == "Société Générale"


def test_quoted_values_may_contain_separators_quotes_and_newlines() -> None:
    content = 'Name,Description\n"Acme, Inc.","Says ""hello""\nover two lines"\n'

    parsed = parse_csv(content.encode())

    assert parsed.rows == [["Acme, Inc.", 'Says "hello"\nover two lines']]


def test_blank_lines_skipped_short_rows_padded_and_line_numbers_kept() -> None:
    parsed = parse_csv(b"Name,City,Country\n\nAcme,Berlin\n  , ,\nGlobex,Paris,FR\n")

    assert parsed.rows == [["Acme", "Berlin", ""], ["Globex", "Paris", "FR"]]
    assert parsed.row_numbers == [3, 5]  # line numbers in the original file


def test_blank_and_duplicate_headers_get_unique_names() -> None:
    parsed = parse_csv(b"Name,,name,Name\na,b,c,d\n")

    assert parsed.headers == ["Name", "Column 2", "name (2)", "Name (3)"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"  \n\n", "empty"),
        (b"Name,City\n", "no data rows"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00", "binary"),
        (b"Name,City\nAcme,Berlin,Germany\n", "more values"),
        (("Name\n" + "x\n" * (MAX_ROWS + 1)).encode(), "maximum"),
        ((",".join(f"c{i}" for i in range(MAX_COLUMNS + 1)) + "\n1\n").encode(), "columns"),
        (b"Name\n" + b"x" * 10_001 + b"\n", "longer than"),
    ],
)
def test_unusable_files_are_rejected_with_a_clear_reason(content: bytes, message: str) -> None:
    with pytest.raises(ImportFileError, match=message):
        parse_csv(content)
