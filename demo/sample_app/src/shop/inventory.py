"""Tiny in-memory inventory with error branches (partially tested)."""


class OutOfStock(Exception):
    pass


_STOCK = {"sku-1": 5, "sku-2": 0}


def reserve(sku: str, qty: int) -> int:
    """Reserve qty of sku; return remaining. Raises on bad input / no stock."""
    if qty <= 0:
        raise ValueError("qty must be positive")
    available = _STOCK.get(sku, 0)
    if qty > available:
        raise OutOfStock(f"{sku}: need {qty}, have {available}")
    return available - qty
