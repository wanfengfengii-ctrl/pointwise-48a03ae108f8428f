import json

from audit.evidence import EvidenceRow
from audit.totals import CategoryTotal
from catalog.snapshots import pin
from catalog.storage import initialize_store, read_transaction
from intake.publish import finish
from intake.requests import SubmissionConflict
from maintenance.compact import compact
from pages.layout import SourcePosition
from pages.objects import load_page
from tests.support import LakeTestCase


class LostReply(Exception):
    pass


class HandoverTests(LakeTestCase):
    def test_pending_page_uses_its_encoding_after_reopen(self):
        a = self.publish('early-a', [('A', 5)])
        pin(self.database, self.partition, 'handover')
        source = self.directory / 'late-station.json'
        source.write_text(json.dumps([['B', 7]]), encoding='utf-8')
        b_binding = self.stage('late-b', json.loads(source.read_text(encoding='utf-8')))
        source.unlink()
        pending = self.pending('late-b')
        self.assertEqual(self.statement().page_ids, (a.page_id,))
        self.assertEqual(self.dictionary(self.initial_dictionary).categories, ('B', 'A'))
        with read_transaction(self.database) as db:
            self.assertEqual(load_page(db, pending.page_id).codes, (0,))
        replacement = compact(self.database, self.partition, (a.page_id,))
        self.assertEqual(self.dictionary(replacement.dictionary_id).categories, ('A',))
        initialize_store(self.database)
        receipt = finish(self.database, b_binding.submission_id, b_binding.fingerprint)
        current = self.statement()
        fixed = self.statement('handover')
        expected_totals = (CategoryTotal('A', 1, 0, 5), CategoryTotal('B', 1, 0, 7))
        self.assertEqual(current.totals, expected_totals, 'CATEGORY_MISATTRIBUTED')
        self.assertEqual(fixed.totals, (CategoryTotal('A', 1, 0, 5),))
        self.assertEqual(fixed.page_ids, (a.page_id,))
        self.assertEqual(current.evidence, (
            EvidenceRow(SourcePosition(self.partition, 'early-a', 1), 'A', 5),
            EvidenceRow(SourcePosition(self.partition, 'late-b', 1), 'B', 7),
        ))
        self.assertEqual(finish(self.database, b_binding.submission_id, b_binding.fingerprint), receipt)
        self.assertEqual(current.page_ids, (replacement.page_id, receipt.page_id))

    def test_late_commit_survives_install_and_lost_reply_replays(self):
        a = self.publish('early-a', [('A', 5)])
        pin(self.database, self.partition, 'before-late')
        b_binding = self.stage('late-b', [('B', 7)])
        delivered = []

        def drop_response(receipt):
            delivered.append(receipt)
            raise LostReply('connection closed after commit')

        def publish_after_selection(selection):
            self.assertEqual(selection.source_ids, (a.page_id,))
            with self.assertRaises(LostReply):
                finish(self.database, b_binding.submission_id, b_binding.fingerprint, after_commit=drop_response)
            self.assertEqual(self.statement().page_ids, (a.page_id, delivered[0].page_id))

        replacement = compact(self.database, self.partition, (a.page_id,), after_select=publish_after_selection)
        initialize_store(self.database)
        receipt = finish(self.database, b_binding.submission_id, b_binding.fingerprint)
        self.assertEqual(delivered, [receipt])
        current = self.statement()
        self.assertEqual(current.totals, (CategoryTotal('A', 1, 0, 5), CategoryTotal('B', 1, 0, 7)))
        self.assertEqual(current.page_ids, (replacement.page_id, receipt.page_id))
        self.assertEqual(current.evidence[-1], EvidenceRow(SourcePosition(self.partition, 'late-b', 1), 'B', 7))
        self.assertEqual(self.statement('before-late').totals, (CategoryTotal('A', 1, 0, 5),))
        with self.assertRaises(SubmissionConflict):
            self.stage('late-b', [('B', 8)])
        self.assertEqual(self.statement(), current)
