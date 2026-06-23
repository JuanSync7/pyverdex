"""Checkout boundary: reads os.environ + json (a runtime-exposed function)."""

import json
import os

from shop.inventory import OutOfStock, reserve
from shop.pricing import final_price


def handle_checkout(payload: str) -> str:
    """Boundary function: parse a checkout request, return a JSON receipt."""
    cart = json.loads(payload)
    vip = os.environ.get("SHOP_VIP") == "1"
    total = sum(i["price"] * i["qty"] for i in cart["items"])
    try:
        for item in cart["items"]:
            reserve(item["sku"], item["qty"])
    except OutOfStock as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "total": final_price(total, vip)})
