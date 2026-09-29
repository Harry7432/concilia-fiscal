import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

ISO_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
DECIMAL_PATTERN = re.compile(r"[+-]?[0-9]+(?:[.,][0-9]{1,2})?")


def parse_iso_date(value: object) -> date:
    if not isinstance(value, str) or ISO_DATE_PATTERN.fullmatch(value) is None:
        raise ValueError
    return date.fromisoformat(value)


def parse_decimal(value: object) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError
    decimal_text = str(value).strip()
    if DECIMAL_PATTERN.fullmatch(decimal_text) is None:
        raise ValueError
    try:
        decimal = Decimal(decimal_text.replace(",", "."))
    except InvalidOperation as error:
        raise ValueError from error
    if not decimal.is_finite() or cast(int, decimal.as_tuple().exponent) < -2:
        raise ValueError
    return decimal
