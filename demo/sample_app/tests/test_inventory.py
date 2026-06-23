from shop.inventory import reserve


def test_reserve_ok():
    assert reserve("sku-1", 2) == 3
