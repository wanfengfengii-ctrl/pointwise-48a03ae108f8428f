from collections.abc import Sequence
from dataclasses import dataclass
import sqlite3

from catalog.partitions import activate_dictionary, active_dictionary
from catalog.storage import write_transaction
from intake.normalize import normalize_submission, submission_fingerprint
from intake.pending import PendingPage, store_pending_page
from pages.dictionaries import create_dictionary, extend_categories
from pages.encode import encode_rows
from pages.objects import store_page


class SubmissionConflict(ValueError):
    """The submission ID already binds different observations."""


@dataclass(frozen=True)
class SubmissionBinding:
    submission_id: str
    partition: str
    fingerprint: str


def load_submission_binding(db: sqlite3.Connection, submission_id: str) -> SubmissionBinding | None:
    row = db.execute(
        'SELECT partition, fingerprint FROM submissions WHERE submission_id = ?', (submission_id,)
    ).fetchone()
    if row is None:
        return None
    return SubmissionBinding(submission_id, row['partition'], row['fingerprint'])


def submit(database, partition: str, submission_id: str, rows: Sequence) -> SubmissionBinding:
    incoming = normalize_submission(partition, submission_id, rows)
    binding = SubmissionBinding(submission_id, partition, submission_fingerprint(incoming))
    with write_transaction(database) as db:
        existing = load_submission_binding(db, submission_id)
        if existing is not None:
            if binding != existing:
                raise SubmissionConflict(f'submission {submission_id!r} already binds different parameters')
            return existing

        dictionary = active_dictionary(db, partition)
        categories = extend_categories(dictionary, (row.category for row in incoming.rows))
        if categories != dictionary.categories:
            dictionary = create_dictionary(db, partition, categories)
            activate_dictionary(db, dictionary)
        page_id = store_page(db, encode_rows(dictionary.categories, incoming.rows))
        db.execute(
            'INSERT INTO submissions (submission_id, partition, fingerprint) VALUES (?, ?, ?)',
            (binding.submission_id, binding.partition, binding.fingerprint),
        )
        store_pending_page(db, PendingPage(submission_id, page_id, dictionary.dictionary_id))
        return binding
