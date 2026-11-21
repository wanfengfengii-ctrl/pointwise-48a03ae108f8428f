from collections.abc import Iterable
from dataclasses import dataclass

from pages.decode import DecodedRow


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    row_count: int
    missing_count: int
    litres: int


def calculate_totals(rows: Iterable[DecodedRow]) -> tuple[CategoryTotal, ...]:
    buckets: dict[str, tuple[int, int, int]] = {}
    for row in rows:
        count, missing, litres = buckets.get(row.category, (0, 0, 0))
        if row.reading is None:
            missing += 1
        else:
            litres += row.reading
        buckets[row.category] = (count + 1, missing, litres)
    return tuple(CategoryTotal(category, *buckets[category]) for category in sorted(buckets))
