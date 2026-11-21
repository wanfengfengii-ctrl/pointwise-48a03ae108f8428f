from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
import json

from pages.layout import SourcePosition, is_coordinate, require_name


@dataclass(frozen=True)
class NormalizedObservation:
    category: str
    reading: int | None
    source: SourcePosition
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class NormalizedSubmission:
    partition: str
    submission_id: str
    rows: tuple[NormalizedObservation, ...]


def _normalize_row(partition: str, submission_id: str, row_number: int, row) -> NormalizedObservation:
    if not isinstance(row, (tuple, list)) or len(row) not in (2, 4):
        raise ValueError(f'row {row_number} must contain category and reading, with optional interval')
    category = require_name(row[0], f'row {row_number} category').strip()
    reading = row[1]
    if reading is not None and type(reading) is not int:
        raise ValueError(f'row {row_number} reading must be an integer litre value or None')
    if len(row) == 2:
        start = end = None
    else:
        start, end = row[2], row[3]
        if not is_coordinate(start) or not is_coordinate(end):
            raise ValueError(f'row {row_number} interval bounds must be integers')
        if start >= end:
            raise ValueError(f'row {row_number} interval start must precede its end')
    source = SourcePosition(partition, submission_id, row_number)
    return NormalizedObservation(category, reading, source, start, end)


def normalize_submission(partition: str, submission_id: str, rows: Sequence) -> NormalizedSubmission:
    require_name(partition, 'partition')
    require_name(submission_id, 'submission ID')
    if isinstance(rows, (str, bytes, bytearray)) or not isinstance(rows, Sequence) or not rows:
        raise ValueError('observations must be a nonempty ordered sequence')
    normalized = []
    row_length: int | None = None
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, (tuple, list)) or len(row) not in (2, 4):
            raise ValueError(f'row {row_number} must contain category and reading, with optional interval')
        if row_length is None:
            row_length = len(row)
        elif row_length != len(row):
            raise ValueError('rows must not mix two-field and four-field layouts')
        normalized.append(_normalize_row(partition, submission_id, row_number, row))
    return NormalizedSubmission(partition, submission_id, tuple(normalized))


def submission_fingerprint(submission: NormalizedSubmission) -> str:
    if any(row.start is not None for row in submission.rows):
        lines = [
            (
                row.category,
                None if row.reading is None else format(row.reading, 'x'),
                format(row.start, 'x'),
                format(row.end, 'x'),
            )
            for row in submission.rows
        ]
    else:
        lines = [
            (row.category, None if row.reading is None else format(row.reading, 'x'))
            for row in submission.rows
        ]
    payload = json.dumps((submission.partition, submission.submission_id, lines), separators=(',', ':'))
    return sha256(payload.encode('ascii')).hexdigest()
