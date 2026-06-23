from shop.pricing import final_price, tier_discount


def test_tier_low():
    assert tier_discount(50) == 0.0
    assert tier_discount(120) == 0.05


def test_final_price_no_vip():
    assert final_price(120) == 114.0
