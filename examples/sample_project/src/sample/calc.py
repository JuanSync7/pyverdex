"""A tiny module with partially-covered branches (smoke target)."""


def classify(n: int) -> str:
    if n < 0:
        return "neg"
    if n == 0:
        return "zero"
    return "pos"


def add(a: int, b: int) -> int:
    return a + b
