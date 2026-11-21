import json

from audit.evidence import EvidenceRow
from audit.totals import CategoryTotal
from catalog.partitions import ensure_partition
from catalog.storage import read_transaction, write_transaction
from intake.publish import finish
from intake.receipts import load_receipt
from intake.requests import SubmissionConflict, load_submission_binding, submit
from pages.layout import PageDataError, SourcePosition
from tests.support import LakeTestCase


class RegistrationRejected(Exception):
    pass


class IntakeTests(LakeTestCase):
    def test_classification_missing_and_evidence(self):
        self.publish('a', [(' A ', 5), ('A', None)])
        self.publish('b', [('B', 7)])
        statement = self.statement()
        self.assertEqual(statement.totals, (CategoryTotal('A', 2, 1, 5), CategoryTotal('B', 1, 0, 7)))
        self.assertEqual(statement.evidence, (
            EvidenceRow(SourcePosition(self.partition, 'a', 1), 'A', 5),
            EvidenceRow(SourcePosition(self.partition, 'a', 2), 'A', None),
            EvidenceRow(SourcePosition(self.partition, 'b', 1), 'B', 7),
        ))

    def test_zero_is_present_and_missing_only_totals_zero(self):
        self.publish('reading', [('A', 0), ('A', None), ('C', None), ('A', 5)])
        statement = self.statement()
        self.assertEqual(statement.totals, (CategoryTotal('A', 3, 1, 5), CategoryTotal('C', 1, 1, 0)))
        self.assertEqual([row.reading for row in statement.evidence], [0, None, None, 5])

    def test_integer_values_remain_exact_and_categories_keep_case(self):
        large = 1 << 20000
        self.publish('reading', [('A', large), ('A', 1 - large), ('a', -2)])
        self.assertEqual(self.statement().totals, (CategoryTotal('A', 2, 0, 1), CategoryTotal('a', 1, 0, -2)))

    def test_invalid_rows_are_rejected_before_any_acceptance(self):
        invalid = ([], [('A', True)], [('A', 1.0)], [('A', '5')], [(' ', 5)], [(None, 5)], [('A', 5, 6)])
        for index, rows in enumerate(invalid):
            submission_id = f'invalid-{index}'
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    self.stage(submission_id, rows)
                with read_transaction(self.database) as db:
                    self.assertIsNone(load_submission_binding(db, submission_id))
                    self.assertIsNone(load_receipt(db, submission_id))
        self.assertEqual(self.statement().totals, ())

    def test_new_categories_are_appended_without_changing_an_older_encoding(self):
        a = self.publish('old', [('A', 5)])
        binding = self.stage('new', [('D', 7), ('C', 0), ('D', None)])
        pending = self.pending(binding.submission_id)
        self.assertEqual(self.dictionary(a.dictionary_id).categories, ('B', 'A'))
        self.assertEqual(self.dictionary(pending.dictionary_id).categories, ('B', 'A', 'D', 'C'))
        self.assertEqual(self.statement().page_ids, (a.page_id,))
        finish(self.database, binding.submission_id, binding.fingerprint)
        self.assertEqual(self.statement().totals, (
            CategoryTotal('A', 1, 0, 5), CategoryTotal('C', 1, 0, 0), CategoryTotal('D', 2, 1, 7),
        ))

    def test_same_binding_replays_and_changed_rows_are_rejected(self):
        binding = self.stage('station', [(' A ', 5), ('A', None), ('B', 7)])
        original_pending = self.pending('station')
        self.assertEqual(self.stage('station', [('A', 5), ('A', None), ('B', 7)]), binding)
        self.assertEqual(self.pending('station'), original_pending)
        receipt = finish(self.database, 'station', binding.fingerprint)
        self.assertEqual(finish(self.database, 'station', binding.fingerprint), receipt)
        for changed in ([('A', 6), ('A', None), ('B', 7)], [('A', None), ('A', 5), ('B', 7)]):
            with self.subTest(changed=changed), self.assertRaises(SubmissionConflict):
                self.stage('station', changed)
        other_partition = '2026-11-22/binting'
        ensure_partition(self.database, other_partition, ('A', 'B'))
        with self.assertRaises(SubmissionConflict):
            submit(self.database, other_partition, 'station', [('A', 5), ('A', None), ('B', 7)])
        with self.assertRaises(SubmissionConflict):
            finish(self.database, 'station', 'a-different-fingerprint')
        statement = self.statement()
        self.assertEqual(statement.page_ids, (receipt.page_id,))
        self.assertEqual(statement.evidence[0], EvidenceRow(SourcePosition(self.partition, 'station', 1), 'A', 5))

    def test_failed_registration_leaves_no_page_or_receipt_and_can_retry(self):
        binding = self.stage('failed-once', [('A', 5)])
        pending = self.pending(binding.submission_id)

        def fail_before_commit():
            raise RegistrationRejected('registration rejected before commit')

        with self.assertRaises(RegistrationRejected):
            finish(self.database, binding.submission_id, binding.fingerprint, before_commit=fail_before_commit)
        self.assertEqual(self.statement().page_ids, ())
        self.assertEqual(self.statement().evidence, ())
        with read_transaction(self.database) as db:
            self.assertIsNone(load_receipt(db, binding.submission_id))
            self.assertIsNone(db.execute('SELECT 1 FROM page_entries WHERE page_id = ?', (pending.page_id,)).fetchone())
        self.assertEqual(self.pending(binding.submission_id), pending)
        receipt = finish(self.database, binding.submission_id, binding.fingerprint)
        self.assertEqual(receipt.page_id, pending.page_id)
        with self.assertRaises(LookupError):
            self.pending(binding.submission_id)
        self.assertEqual(finish(self.database, binding.submission_id, binding.fingerprint), receipt)
        self.assertEqual(self.statement().totals, (CategoryTotal('A', 1, 0, 5),))

    def test_required_page_corruption_rejects_the_entire_statement(self):
        self.publish('a', [('A', 5)])
        b = self.publish('b', [('B', 7)])
        self.assertEqual(len(self.statement().evidence), 2)
        with read_transaction(self.database) as db:
            original = db.execute('SELECT body FROM page_objects WHERE page_id = ?', (b.page_id,)).fetchone()['body']
        for column, replacement in (
            ('codes', []), ('codes', [99]), ('codes', [False]),
            ('readings', [True]), ('sources', [[self.partition, 'b', 0]]),
        ):
            with self.subTest(column=column, replacement=replacement):
                payload = json.loads(original)
                payload[column] = replacement
                with write_transaction(self.database) as db:
                    db.execute('UPDATE page_objects SET body = ? WHERE page_id = ?', (json.dumps(payload), b.page_id))
                with self.assertRaises(PageDataError):
                    self.statement()
