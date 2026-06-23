from sample.calc import add, classify


def test_add():
    assert add(2, 3) == 5


def test_classify_pos():
    assert classify(5) == "pos"
