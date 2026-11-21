import json
import sqlite3

from pages.layout import PageBody, PageDataError, SourcePosition, validate_layout


def store_page(db: sqlite3.Connection, body: PageBody) -> int:
    validate_layout(body)
    starts = body.starts if body.starts is not None else (None,) * len(body.codes)
    ends = body.ends if body.ends is not None else (None,) * len(body.codes)
    payload = {
        'codes': body.codes,
        'readings': [None if value is None else format(value, 'x') for value in body.readings],
        'sources': [(source.partition, source.submission_id, source.row_number) for source in body.sources],
        'starts': [None if value is None else format(value, 'x') for value in starts],
        'ends': [None if value is None else format(value, 'x') for value in ends],
    }
    cursor = db.execute(
        'INSERT INTO page_objects (body) VALUES (?)',
        (json.dumps(payload, separators=(',', ':')),),
    )
    return cursor.lastrowid


def _load_reading(value: str | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('stored reading must be hexadecimal text or null')
    reading = int(value, 16)
    if format(reading, 'x') != value:
        raise ValueError('noncanonical stored reading')
    return reading


def _load_source(value: list) -> SourcePosition:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError('stored source must contain partition, submission ID and row number')
    return SourcePosition(*value)


def _load_coordinate(value: str | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('stored coordinate must be hexadecimal text or null')
    coordinate = int(value, 16)
    if format(coordinate, 'x') != value:
        raise ValueError('noncanonical stored coordinate')
    return coordinate


def load_page(db: sqlite3.Connection, page_id: int) -> PageBody:
    row = db.execute('SELECT body FROM page_objects WHERE page_id = ?', (page_id,)).fetchone()
    if row is None:
        raise PageDataError(f'page body {page_id} is unavailable')
    try:
        payload = json.loads(row['body'])
        columns = ('codes', 'readings', 'sources')
        if not isinstance(payload, dict):
            raise ValueError('stored page has an invalid column layout')
        if not set(columns) <= set(payload) or set(payload) - set(columns) - {'starts', 'ends'}:
            raise ValueError('stored page has an invalid column layout')
        if not all(isinstance(payload[column], list) for column in columns):
            raise ValueError('stored columns must be lists')
        starts = payload.get('starts')
        ends = payload.get('ends')
        if starts is None and ends is None:
            starts = [None] * len(payload['codes'])
            ends = [None] * len(payload['codes'])
        elif starts is None or ends is None:
            raise ValueError('stored interval columns must both be present')
        if not isinstance(starts, list) or not isinstance(ends, list):
            raise ValueError('stored interval columns must be lists')
        body = PageBody(
            tuple(payload['codes']),
            tuple(_load_reading(value) for value in payload['readings']),
            tuple(_load_source(value) for value in payload['sources']),
            tuple(_load_coordinate(value) for value in starts),
            tuple(_load_coordinate(value) for value in ends),
        )
        validate_layout(body)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PageDataError(f'invalid body for page {page_id}') from exc
    return body
