"""Reading uploaded CSV files robustly and safely (pure functions, no database).

Real-world CSVs come from Excel, Google Sheets, CRMs and hand edits, so we handle:
- encodings: UTF-8 (with or without Excel's byte-order mark), falling back to Windows-1252;
- separators: comma, semicolon (European Excel), tab, pipe;
- blank lines, blank or duplicate headers, short rows.

Hard limits protect the server from oversized or malicious files.
"""

import csv
import io
import re
from dataclasses import dataclass

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 100
MAX_CELL_CHARS = 10_000
_DELIMITERS = ",;\t|"


class ImportFileError(ValueError):
    """The file as a whole cannot be imported (as opposed to individual bad rows)."""


@dataclass(frozen=True)
class ParsedCsv:
    headers: list[str]
    rows: list[list[str]]  # each row padded to len(headers)
    row_numbers: list[int]  # 1-based line number in the file, for error messages
    encoding: str
    delimiter: str


def _decode(content: bytes) -> tuple[str, str]:
    if b"\x00" in content[:4096]:
        raise ImportFileError("This looks like a binary file, not CSV. Export as .csv first.")
    try:
        return content.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace"), "windows-1252"


def _detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
    except csv.Error:
        first_line = text.splitlines()[0] if text else ""
        return max(_DELIMITERS, key=first_line.count) if first_line else ","


def _clean_headers(raw: list[str]) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(raw, start=1):
        header = re.sub(r"\s+", " ", value).strip() or f"Column {index}"
        if header.lower() in seen:
            seen[header.lower()] += 1
            header = f"{header} ({seen[header.lower()]})"
        else:
            seen[header.lower()] = 1
        headers.append(header)
    return headers


def parse_csv(content: bytes) -> ParsedCsv:
    if not content.strip():
        raise ImportFileError("The file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise ImportFileError(f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")

    text, encoding = _decode(content)
    delimiter = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=False)

    try:
        records = [(reader.line_num, row) for row in reader]
    except csv.Error as exc:
        raise ImportFileError(f"The file is not valid CSV: {exc}") from exc

    records = [(line, row) for line, row in records if any(cell.strip() for cell in row)]
    if not records:
        raise ImportFileError("The file is empty.")

    _, header_row = records[0]
    if len(header_row) > MAX_COLUMNS:
        raise ImportFileError(f"The file has more than {MAX_COLUMNS} columns.")
    headers = _clean_headers(header_row)
    data = records[1:]
    if not data:
        raise ImportFileError("The file has a header row but no data rows.")
    if len(data) > MAX_ROWS:
        raise ImportFileError(
            f"The file has {len(data):,} rows; the maximum is {MAX_ROWS:,} per import."
        )

    rows: list[list[str]] = []
    for line, row in data:
        if len(row) > len(headers) and any(cell.strip() for cell in row[len(headers) :]):
            raise ImportFileError(
                f"Line {line} has more values than there are column headers. "
                "Check the separator and quoting."
            )
        if any(len(cell) > MAX_CELL_CHARS for cell in row):
            raise ImportFileError(
                f"Line {line} has a value longer than {MAX_CELL_CHARS} characters."
            )
        cells = [cell.strip() for cell in row[: len(headers)]]
        rows.append(cells + [""] * (len(headers) - len(cells)))

    return ParsedCsv(
        headers=headers,
        rows=rows,
        row_numbers=[line for line, _ in data],
        encoding=encoding,
        delimiter=delimiter,
    )
