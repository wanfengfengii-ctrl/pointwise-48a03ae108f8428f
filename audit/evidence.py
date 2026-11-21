from collections.abc import Iterable
from dataclasses import dataclass

from pages.decode import DecodedRow
from pages.layout import SourcePosition


@dataclass(frozen=True)
class EvidenceRow:
    source: SourcePosition
    category: str
    reading: int | None


def build_evidence(rows: Iterable[DecodedRow]) -> tuple[EvidenceRow, ...]:
    return tuple(
        EvidenceRow(row.source, row.category, row.reading)
        for row in sorted(rows, key=lambda row: row.source)
    )
