from dataclasses import dataclass
from fractions import Fraction

from audit.resolve import resolve_view
from audit.rows import load_view_rows
from catalog.storage import read_transaction
from pages.decode import DecodedRow
from pages.layout import SourcePosition, is_coordinate, require_name


@dataclass(frozen=True)
class CoverageSegment:
    category: str
    start: int
    end: int
    state: str
    litres: Fraction | None
    overlap: str
    sources: tuple[SourcePosition, ...]


@dataclass(frozen=True)
class CoverageConflict:
    category: str
    start: int
    end: int
    sources: tuple[SourcePosition, ...]
    rates: tuple[Fraction | None, ...]


@dataclass(frozen=True)
class CoverageStatement:
    partition: str
    snapshot_id: str | None
    requested_start: int
    requested_end: int
    status: str
    reason: str | None
    segments: tuple[CoverageSegment, ...]
    total_litres: Fraction
    missing_length: int
    uncovered_length: int
    conflict: CoverageConflict | None


class _Rejected(Exception):
    def __init__(self, conflict: CoverageConflict):
        self.conflict = conflict


def _rate(row: DecodedRow) -> Fraction:
    return Fraction(row.reading, row.end - row.start)


def _covers(row: DecodedRow, start: int, end: int) -> bool:
    return row.start <= start and row.end >= end


def _category_segments(
    category: str, rows: tuple[DecodedRow, ...], start: int, end: int
) -> tuple[list[CoverageSegment], int, int]:
    boundaries = {start, end}
    for row in rows:
        if row.start < end and row.end > start:
            boundaries.add(max(row.start, start))
            boundaries.add(min(row.end, end))
    ordered = sorted(boundaries)
    segments: list[CoverageSegment] = []
    missing_length = 0
    uncovered_length = 0
    for left, right in zip(ordered[:-1], ordered[1:]):
        if left == right:
            continue
        active = tuple(sorted((row for row in rows if _covers(row, left, right)), key=lambda row: row.source))
        if not active:
            segments.append(CoverageSegment(category, left, right, 'uncovered', None, 'uncovered', ()))
            uncovered_length += right - left
            continue
        effective = tuple(row for row in active if row.reading is not None)
        if not effective:
            segments.append(CoverageSegment(
                category, left, right, 'missing', None, 'missing-only', tuple(row.source for row in active)
            ))
            missing_length += right - left
            continue
        if len(effective) != len(active):
            raise _Rejected(CoverageConflict(
                category, left, right,
                tuple(row.source for row in active),
                tuple(None if row.reading is None else _rate(row) for row in active),
            ))
        rates = tuple(_rate(row) for row in effective)
        if len(set(rates)) != 1:
            raise _Rejected(CoverageConflict(
                category, left, right,
                tuple(row.source for row in effective),
                rates,
            ))
        rate = rates[0]
        overlap = 'none' if len(effective) == 1 else 'same-rate'
        segments.append(CoverageSegment(
            category, left, right, 'value', rate * (right - left), overlap,
            tuple(row.source for row in effective),
        ))
    return segments, missing_length, uncovered_length


def _coverage(partition: str, snapshot_id: str | None, start: int, end: int,
              rows: tuple[DecodedRow, ...]) -> CoverageStatement:
    by_category: dict[str, list[DecodedRow]] = {}
    for row in rows:
        if not row.has_interval:
            continue
        if row.start < end and row.end > start:
            by_category.setdefault(row.category, []).append(row)

    segments: list[CoverageSegment] = []
    missing_length = 0
    uncovered_length = 0
    try:
        for category in sorted(by_category):
            category_segments, category_missing, category_uncovered = _category_segments(
                category, tuple(by_category[category]), start, end
            )
            segments.extend(category_segments)
            missing_length += category_missing
            uncovered_length += category_uncovered
    except _Rejected as rejected:
        return CoverageStatement(
            partition, snapshot_id, start, end, 'rejected', 'conflicting-overlap',
            (), Fraction(0), 0, 0, rejected.conflict,
        )

    total = sum((segment.litres for segment in segments if segment.litres is not None), Fraction(0))
    return CoverageStatement(
        partition, snapshot_id, start, end, 'ok', None,
        tuple(segments), total, missing_length, uncovered_length, None,
    )


def read_coverage(database, partition: str, start: int, end: int,
                  snapshot_id: str | None = None) -> CoverageStatement:
    """Resolve exact interval coverage from one complete lake view."""
    require_name(partition, 'partition')
    if snapshot_id is not None:
        require_name(snapshot_id, 'snapshot ID')
    if not is_coordinate(start) or not is_coordinate(end):
        raise ValueError('query coordinates must be integers')
    if start >= end:
        raise ValueError('query start must precede its end')
    with read_transaction(database) as db:
        view = resolve_view(db, partition, snapshot_id)
        rows = load_view_rows(db, view)
        return _coverage(view.partition, view.snapshot_id, start, end, rows)
