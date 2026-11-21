from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class PendingPage:
    submission_id: str
    page_id: int
    dictionary_id: int


def store_pending_page(db: sqlite3.Connection, pending: PendingPage) -> None:
    db.execute(
        'INSERT INTO pending_pages (submission_id, page_id, dictionary_id) VALUES (?, ?, ?)',
        (pending.submission_id, pending.page_id, pending.dictionary_id),
    )


def read_pending_page(db: sqlite3.Connection, submission_id: str) -> PendingPage:
    row = db.execute(
        'SELECT page_id, dictionary_id FROM pending_pages WHERE submission_id = ?', (submission_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f'no pending page for {submission_id!r}')
    return PendingPage(submission_id, row['page_id'], row['dictionary_id'])


def remove_pending_page(db: sqlite3.Connection, submission_id: str) -> None:
    cursor = db.execute('DELETE FROM pending_pages WHERE submission_id = ?', (submission_id,))
    if cursor.rowcount != 1:
        raise LookupError(f'no pending page for {submission_id!r}')
