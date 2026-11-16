"""Validate a bounded CSV upload and preserve physical source line numbers."""

import csv
import io
import re
import unicodedata
from decimal import Decimal

from pydantic import ValidationError

from amacfa.models import Evidence, Invoice, canonical_digest

COLUMNS = tuple(Invoice.model_fields)
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
AMOUNT = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,2})?")


class InvoiceInputError(ValueError):
    """CSV input failed validation. Messages intentionally omit cell values."""


def parse_invoice_csv(payload: bytes, max_rows: int) -> list[Evidence]:
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvoiceInputError("CSV must use UTF-8.") from exc

    reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
    rows: list[Evidence] = []
    try:
        header = next(reader, [])
        if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
            raise InvoiceInputError(f"Expected exactly these columns: {', '.join(COLUMNS)}.")
        while True:
            line = reader.line_num + 1
            cells = next(reader, None)
            if cells is None:
                break
            if not cells:
                continue
            if len(rows) >= max_rows:
                raise InvoiceInputError(f"CSV exceeds the limit of {max_rows} invoices.")
            if len(cells) != len(header) or reader.line_num != line:
                raise InvoiceInputError(f"Line {line}: expected a single, complete invoice record.")
            record = {
                key: unicodedata.normalize("NFKC", value).strip()
                for key, value in zip(header, cells, strict=True)
            }
            rows.append(_parse_record(record, line))
    except csv.Error as exc:
        raise InvoiceInputError(f"Invalid CSV near line {reader.line_num}.") from exc
    if not rows:
        raise InvoiceInputError("CSV must contain at least one invoice.")
    return rows


def _parse_record(record: dict[str, str], line: int) -> Evidence:
    normalized = dict.fromkeys(COLUMNS)
    normalized.update({key: value.upper() or None for key, value in record.items()})
    if not DATE.fullmatch(record["issued_on"]) or not AMOUNT.fullmatch(record["amount"]):
        raise InvoiceInputError(f"Line {line}: use YYYY-MM-DD and a positive decimal amount.")
    try:
        invoice = Invoice.model_validate(normalized)
    except ValidationError as exc:
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors(include_input=False))
        raise InvoiceInputError(f"Line {line}: invalid field(s): {fields}.") from exc
    if invoice.currency == "VND" and invoice.amount % 1:
        raise InvoiceInputError(f"Line {line}: VND amount must be an integer.")
    quantum = Decimal("1") if invoice.currency == "VND" else Decimal("0.01")
    invoice.amount = invoice.amount.quantize(quantum)
    return Evidence(
        line=line, invoice=invoice, row_sha256=canonical_digest(invoice.model_dump(mode="json"))
    )
