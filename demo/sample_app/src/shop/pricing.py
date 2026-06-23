"""Pure pricing logic with tiered discount branches (partially tested)."""


def tier_discount(total: float) -> float:
    """Discount fraction by spend tier."""
    if total >= 1000:
        return 0.20
    if total >= 500:
        return 0.10
    if total >= 100:
        return 0.05
    return 0.0


def final_price(total: float, vip: bool = False) -> float:
    """Apply tier discount, plus a VIP bonus capped at 30%."""
    disc = tier_discount(total)
    if vip:
        disc = min(disc + 0.05, 0.30)
    return round(total * (1 - disc), 2)
