from audit.evidence import EvidenceRow
from audit.statement import read
from audit.totals import CategoryTotal
from catalog.partitions import ensure_partition
from catalog.snapshots import pin
from catalog.storage import read_transaction
from intake.publish import finish
from maintenance.compact import compact
from maintenance.select import StaleSources
from pages.layout import SourcePosition
from pages.objects import load_page
from tests.support import LakeTestCase


class CompactionTests(LakeTestCase):
    def test_compaction_prunes_unused_codes_and_preserves_snapshot_and_evidence(self):
        page = self.publish('first', [('A', 5), ('A', None)])
        before = self.statement()
        self.assertEqual(pin(self.database, self.partition, 'shift'), (page.page_id,))
        replacement = compact(self.database, self.partition, before.page_ids)
        self.assertEqual(self.dictionary(replacement.dictionary_id).categories, ('A',))
        self.assertEqual(self.dictionary(page.dictionary_id).categories, ('B', 'A'))
        with read_transaction(self.database) as db:
            self.assertEqual(load_page(db, replacement.page_id).codes, (0, 0))
        current = self.statement()
        fixed = self.statement('shift')
        self.assertEqual(current.page_ids, (replacement.page_id,))
        self.assertEqual(fixed.page_ids, (page.page_id,))
        self.assertEqual(current.totals, (CategoryTotal('A', 2, 1, 5),))
        self.assertEqual((current.totals, current.evidence), (fixed.totals, fixed.evidence))
        self.assertEqual(current.evidence, (
            EvidenceRow(SourcePosition(self.partition, 'first', 1), 'A', 5),
            EvidenceRow(SourcePosition(self.partition, 'first', 2), 'A', None),
        ))

    def test_rewrite_uses_each_sources_dictionary_and_original_positions(self):
        a = self.publish('z-a', [('A', 5), ('A', None)])
        b_binding = self.stage('a-b', [('B', 7)])
        new_a = compact(self.database, self.partition, (a.page_id,))
        b = finish(self.database, b_binding.submission_id, b_binding.fingerprint)
        self.assertNotEqual(new_a.dictionary_id, b.dictionary_id)
        with read_transaction(self.database) as db:
            self.assertEqual(load_page(db, new_a.page_id).codes, (0, 0))
            self.assertEqual(load_page(db, b.page_id).codes, (0,))
        pin(self.database, self.partition, 'mixed')
        merged = compact(self.database, self.partition, (b.page_id, new_a.page_id))
        self.assertEqual(self.dictionary(merged.dictionary_id).categories, ('A', 'B'))
        statement = self.statement()
        self.assertEqual(statement.page_ids, (merged.page_id,))
        self.assertEqual(statement.evidence, self.statement('mixed').evidence)
        self.assertEqual(statement.totals, (CategoryTotal('A', 2, 1, 5), CategoryTotal('B', 1, 0, 7)))
        self.assertEqual(statement.evidence, (
            EvidenceRow(SourcePosition(self.partition, 'a-b', 1), 'B', 7),
            EvidenceRow(SourcePosition(self.partition, 'z-a', 1), 'A', 5),
            EvidenceRow(SourcePosition(self.partition, 'z-a', 2), 'A', None),
        ))

    def test_nonselected_pages_keep_relative_order(self):
        pages = [self.publish(name, [(category, value)]) for name, category, value in (
            ('one', 'A', 1), ('two', 'B', 2), ('three', 'B', 3), ('four', 'A', 4),
        )]
        replacement = compact(self.database, self.partition, (pages[2].page_id, pages[0].page_id))
        statement = self.statement()
        self.assertEqual(statement.page_ids, (replacement.page_id, pages[1].page_id, pages[3].page_id))
        self.assertEqual(statement.totals, (CategoryTotal('A', 2, 0, 5), CategoryTotal('B', 2, 0, 5)))
        with read_transaction(self.database) as db:
            body = load_page(db, replacement.page_id)
        self.assertEqual([position.submission_id for position in body.sources], ['one', 'three'])

    def test_stale_sources_abort_install_after_other_compaction_wins(self):
        a = self.publish('first', [('A', 5)])
        winners = []

        def replace_selected(selection):
            winners.append(compact(self.database, self.partition, selection.source_ids))

        with self.assertRaises(StaleSources):
            compact(self.database, self.partition, (a.page_id,), after_select=replace_selected)
        winner, = winners
        self.assertEqual(self.statement().page_ids, (winner.page_id,))
        self.assertEqual(self.statement().totals, (CategoryTotal('A', 1, 0, 5),))
        with read_transaction(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM page_objects').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dictionaries').fetchone()[0], 2)

    def test_snapshot_members_are_fixed_and_number_conflicts_are_global(self):
        a = self.publish('first', [('A', 5)])
        pin(self.database, self.partition, 'shift')
        compact(self.database, self.partition, (a.page_id,))
        self.publish('later', [('B', 7)])
        separate = '2026-11-22/binting'
        ensure_partition(self.database, separate, ('A',))
        with self.assertRaises(ValueError):
            pin(self.database, separate, 'shift')
        with self.assertRaises(LookupError):
            read(self.database, separate, 'shift')
        self.assertEqual(self.statement('shift').page_ids, (a.page_id,))
        self.assertEqual(self.statement('shift').totals, (CategoryTotal('A', 1, 0, 5),))
        self.assertEqual(self.statement().totals, (CategoryTotal('A', 1, 0, 5), CategoryTotal('B', 1, 0, 7)))
        self.assertEqual(pin(self.database, separate, 'empty'), ())
        self.assertEqual(read(self.database, separate, 'empty').evidence, ())

    def test_invalid_source_selection_keeps_current_members(self):
        a = self.publish('first', [('A', 5)])
        for source_ids in ((), (a.page_id, a.page_id), (True,)):
            with self.subTest(source_ids=source_ids), self.assertRaises(ValueError):
                compact(self.database, self.partition, source_ids)
        with self.assertRaises(StaleSources):
            compact(self.database, self.partition, (a.page_id + 1,))
        self.assertEqual(self.statement().page_ids, (a.page_id,))
