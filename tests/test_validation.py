from datetime import date, timedelta

from app.schemas.invoice import InvoiceFields, LineItem
from app.services.validation import validate_invoice


def _invoice(**overrides) -> InvoiceFields:
    defaults = {
        "invoice_number": "INV-001",
        "date": "2026-01-15",
        "vendor": "Acme Corp",
        "line_items": [LineItem(description="Widget", quantity=2, unit_price=10.0, amount=20.0)],
        "total": 20.0,
    }
    defaults.update(overrides)
    return InvoiceFields(**defaults)


def test_valid_invoice_has_no_errors() -> None:
    assert validate_invoice(_invoice()) == []


def test_mismatched_total_is_flagged() -> None:
    errors = validate_invoice(_invoice(total=999.0))

    assert len(errors) == 1
    field, message = errors[0]
    assert field == "total"
    assert "999" in message


def test_unparseable_date_is_flagged() -> None:
    errors = validate_invoice(_invoice(date="not a date"))

    assert len(errors) == 1
    assert errors[0][0] == "date"


def test_future_date_is_flagged() -> None:
    future = (date.today() + timedelta(days=30)).isoformat()

    errors = validate_invoice(_invoice(date=future))

    assert len(errors) == 1
    assert errors[0][0] == "date"


def test_multiple_failures_are_all_reported() -> None:
    errors = validate_invoice(_invoice(total=999.0, date="not a date"))

    fields_with_errors = {field for field, _ in errors}
    assert fields_with_errors == {"total", "date"}


def test_invoice_with_tax_and_adjustments_that_reconcile_has_no_errors() -> None:
    # line items sum to 20.0 (the default fixture); subtotal matches, and
    # 20.0 + 3.6 tax - 0 discount - 5.0 adjustment = 18.6
    errors = validate_invoice(
        _invoice(subtotal=20.0, tax_amount=3.6, adjustment_amount=-5.0, total=18.6)
    )

    assert errors == []


def test_invoice_with_subtotal_not_matching_line_items_is_flagged() -> None:
    errors = validate_invoice(_invoice(subtotal=50.0, total=50.0))

    assert len(errors) == 1
    assert errors[0][0] == "subtotal"


def test_invoice_with_tax_math_that_doesnt_reconcile_is_still_flagged() -> None:
    # subtotal matches line items, but total ignores the stated tax
    errors = validate_invoice(_invoice(subtotal=20.0, tax_amount=3.6, total=20.0))

    assert len(errors) == 1
    assert errors[0][0] == "total"
