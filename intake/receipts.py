from dataclasses import dataclass
import sqlite3

from catalog.manifests import PageEntry


@dataclass(frozen=True)
class Receipt:
    submission_id: str
    partition: str
    page_id: int
    dictionary_id: int


def issue_receipt(db: sqlite3.Connection, submission_id: str, entry: PageEntry) -> Receipt:
    db.execute('INSERT INTO receipts (submission_id, page_id) VALUES (?, ?)', (submission_id, entry.page_id))
    return Receipt(submission_id, entry.partition, entry.page_id, entry.dictionary_id)


def load_receipt(db: sqlite3.Connection, submission_id: str) -> Receipt | None:
    row = db.execute(
        'SELECT pages.partition, receipts.page_id, pages.dictionary_id FROM receipts '
        'JOIN page_entries AS pages USING (page_id) WHERE submission_id = ?', (submission_id,)
    ).fetchone()
    if row is None:
        return None
    return Receipt(submission_id, row['partition'], row['page_id'], row['dictionary_id'])
