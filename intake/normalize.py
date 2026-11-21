from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
import json

from pages.layout import SourcePosition, require_name


@dataclass(frozen=True)
class NormalizedObservation:
    category: str
    reading: int | None
    source: SourcePosition


@dataclass(frozen=True)
class NormalizedSubmission:
    partition: str
    submission_id: str
    rows: tuple[NormalizedObservation, ...]


def normalize_submission(partition: str, submission_id: str, rows: Sequence) -> NormalizedSubmission:
    require_name(partition, 'partition')
    require_name(submission_id, 'submission ID')
    if isinstance(rows, (str, bytes, bytearray)) or not isinstance(rows, Sequence) or not rows:
        raise ValueError('observations must be a nonempty ordered sequence')
    normalized = []
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise ValueError(f'row {row_number} must contain category and reading')
        category, reading = row
        category = require_name(category, f'row {row_number} category').strip()
        if reading is not None and type(reading) is not int:
            raise ValueError(f'row {row_number} reading must be an integer litre value or None')
        source = SourcePosition(partition, submission_id, row_number)
        normalized.append(NormalizedObservation(category, reading, source))
    return NormalizedSubmission(partition, submission_id, tuple(normalized))


def submission_fingerprint(submission: NormalizedSubmission) -> str:
    lines = [
        (row.category, None if row.reading is None else format(row.reading, 'x'))
        for row in submission.rows
    ]
    payload = json.dumps((submission.partition, submission.submission_id, lines), separators=(',', ':'))
    return sha256(payload.encode('ascii')).hexdigest()
