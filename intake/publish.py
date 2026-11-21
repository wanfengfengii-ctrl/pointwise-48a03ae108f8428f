from collections.abc import Callable

from catalog.manifests import append_member, register_page
from catalog.storage import write_transaction
from intake.pending import read_pending_page, remove_pending_page
from intake.receipts import Receipt, issue_receipt, load_receipt
from intake.requests import SubmissionConflict, load_submission_binding
from pages.decode import decode_page
from pages.dictionaries import load_dictionary
from pages.layout import PageDataError, SourcePosition, require_name
from pages.objects import load_page


def finish(
    database,
    submission_id: str,
    fingerprint: str,
    *,
    before_commit: Callable[[], None] | None = None,
    after_commit: Callable[[Receipt], None] | None = None,
) -> Receipt:
    """Publish a staged submission or return its original receipt."""
    require_name(submission_id, 'submission ID')
    require_name(fingerprint, 'binding fingerprint')
    with write_transaction(database) as db:
        binding = load_submission_binding(db, submission_id)
        if binding is None:
            raise LookupError(f'unknown submission {submission_id!r}')
        if fingerprint != binding.fingerprint:
            raise SubmissionConflict(f'fingerprint does not match submission {submission_id!r}')
        original = load_receipt(db, submission_id)
        if original is not None:
            return original

        pending = read_pending_page(db, submission_id)
        dictionary = load_dictionary(db, binding.partition, pending.dictionary_id)
        rows = decode_page(load_page(db, pending.page_id), dictionary)
        for position, row in enumerate(rows, start=1):
            if row.source != SourcePosition(binding.partition, submission_id, position):
                raise PageDataError(f'page {pending.page_id} does not match the submission source positions')

        page = register_page(db, pending.page_id, binding.partition, dictionary.dictionary_id)
        append_member(db, page)
        receipt = issue_receipt(db, submission_id, page)
        remove_pending_page(db, submission_id)
        if before_commit is not None:
            before_commit()
    if after_commit is not None:
        after_commit(receipt)
    return receipt
