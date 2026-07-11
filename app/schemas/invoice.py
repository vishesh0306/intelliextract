from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    amount: float


class InvoiceFields(BaseModel):
    """Structured fields extracted from an invoice by the LLM.

    `date` is deliberately a string, not a `date` type: the spec treats
    "dates are parseable and not in the future" as a business rule
    (Phase 7), not schema validation. If Pydantic rejected unparseable
    dates here, that business rule would never get a chance to run and
    feed a useful correction back into the retry prompt.
    """

    invoice_number: str
    date: str = Field(description="Invoice date as YYYY-MM-DD if determinable")
    vendor: str
    line_items: list[LineItem]
    total: float
