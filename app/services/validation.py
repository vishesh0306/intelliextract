from datetime import date, datetime

from app.schemas.invoice import InvoiceFields

# Business rules, not schema validation — Pydantic already guarantees types
# and required fields by the time an InvoiceFields instance exists. These
# are checks a syntactically valid invoice can still fail (the numbers
# don't add up, the date is nonsense) — exactly what the self-correction
# retry loop exists to catch.

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y")
_AMOUNT_TOLERANCE = 0.01


def validate_invoice(fields: InvoiceFields) -> list[tuple[str, str]]:
    """Returns (field_name, message) pairs — empty if the invoice passes
    every business rule. field_name lets the confidence scorer and the
    retry re-prompt both know exactly which field to distrust/fix, instead
    of parsing that back out of free-text error messages.
    """
    errors: list[tuple[str, str]] = []

    line_items_sum = sum(item.amount for item in fields.line_items)
    if abs(line_items_sum - fields.total) > _AMOUNT_TOLERANCE:
        errors.append(
            (
                "total",
                f"Line item amounts sum to {line_items_sum:.2f} but total is "
                f"{fields.total:.2f} — they should match. Re-check each line item's "
                f"amount and the total.",
            )
        )

    parsed_date = _try_parse_date(fields.date)
    if parsed_date is None:
        errors.append(("date", f"'{fields.date}' is not a recognizable date. Use YYYY-MM-DD."))
    elif parsed_date > date.today():
        errors.append(
            ("date", f"'{fields.date}' is in the future, which isn't valid for an invoice date.")
        )

    return errors


def _try_parse_date(value: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
