from fractions import Fraction

from audit.coverage import CoverageConflict, read_coverage
from catalog.partitions import ensure_partition
from catalog.snapshots import pin, release
from catalog.storage import initialize_store, read_transaction, write_transaction
from intake.publish import finish
from intake.requests import SubmissionConflict, submit
from maintenance.compact import compact
from maintenance.reclaim import reclaim
from pages.layout import PageDataError
from tests.support import LakeTestCase


class CoverageTests(LakeTestCase):
    def coverage(self, start, end, snapshot_id=None):
        return read_coverage(self.database, self.partition, start, end, snapshot_id)

    def shape(self, statement):
        return [
            (segment.category, segment.start, segment.end, segment.state,
             None if segment.litres is None else str(segment.litres), segment.overlap,
             tuple((source.submission_id, source.row_number) for source in segment.sources))
            for segment in statement.segments
        ]

    def test_four_field_rows_need_matching_lengths_integers_and_start_before_end(self):
        invalid = (
            [('A', 1, 0, 0)],
            [('A', 1, 2, 1)],
            [('A', 1, 0, True)],
            [('A', 1, False, 4)],
            [('A', 1, 0.0, 4)],
            [('A', True, 0, 4)],
            [('A', 1, 0, 4), ('A', 2)],
            [('A', 1), ('A', 2, 0, 4)],
        )
        for index, rows in enumerate(invalid):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.stage(f'bad-{index}', rows)
        self.assertEqual(self.statement().totals, ())

    def test_same_rate_overlap_counts_once_with_every_source(self):
        self.publish('sample-a', [('A', 8, 0, 4)])
        self.publish('sample-b', [('A', 8, 2, 6)])
        result = self.coverage(1, 5)
        self.assertEqual(result.status, 'ok')
        self.assertIsNone(result.reason)
        self.assertEqual(result.total_litres, Fraction(8))
        self.assertEqual(self.shape(result), [
            ('A', 1, 2, 'value', '2', 'none', (('sample-a', 1),)),
            ('A', 2, 4, 'value', '4', 'same-rate', (('sample-a', 1), ('sample-b', 1))),
            ('A', 4, 5, 'value', '2', 'none', (('sample-b', 1),)),
        ])
        self.assertEqual(result.missing_length, 0)
        self.assertEqual(result.uncovered_length, 0)
        self.assertIsNone(result.conflict)

    def test_conflicting_rates_reject_whole_query_without_mutation(self):
        self.publish('sample-a', [('A', 8, 0, 4)])
        self.publish('sample-b', [('A', 10, 2, 6)])
        before = self.statement()
        result = self.coverage(1, 5)
        self.assertEqual((result.status, result.reason), ('rejected', 'conflicting-overlap'))
        self.assertEqual(result.segments, ())
        self.assertEqual(result.total_litres, Fraction(0))
        self.assertEqual(result.missing_length, 0)
        self.assertEqual(result.uncovered_length, 0)
        self.assertIsInstance(result.conflict, CoverageConflict)
        self.assertEqual(
            (result.conflict.category, result.conflict.start, result.conflict.end),
            ('A', 2, 4),
        )
        self.assertEqual(result.conflict.rates, (Fraction(2), Fraction(5, 2)))
        self.assertEqual(self.statement(), before)

    def test_missing_overlapping_a_value_rejects_the_query(self):
        self.publish('valued', [('A', 8, 0, 4)])
        self.publish('unknown', [('A', None, 2, 6)])
        result = self.coverage(1, 5)
        self.assertEqual((result.status, result.reason), ('rejected', 'conflicting-overlap'))
        self.assertEqual(result.conflict.rates, (None, Fraction(2)))

    def test_zero_value_is_not_missing_and_missing_is_not_uncovered(self):
        self.publish('zero-c', [('C', 0, 0, 4)])
        self.publish('missing-d', [('D', None, 2, 6)])
        result = self.coverage(1, 5)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.total_litres, Fraction(0))
        self.assertEqual(result.missing_length, 3)
        self.assertEqual(result.uncovered_length, 2)
        self.assertEqual(self.shape(result), [
            ('C', 1, 4, 'value', '0', 'none', (('zero-c', 1),)),
            ('C', 4, 5, 'uncovered', None, 'uncovered', ()),
            ('D', 1, 2, 'uncovered', None, 'uncovered', ()),
            ('D', 2, 5, 'missing', None, 'missing-only', (('missing-d', 1),)),
        ])

    def test_overlapping_missing_only_lines_share_one_missing_segment(self):
        self.publish('m1', [('A', None, 0, 4)])
        self.publish('m2', [('A', None, 2, 6)])
        result = self.coverage(1, 5)
        self.assertEqual(result.status, 'ok')
        self.assertEqual([segment.state for segment in result.segments], ['missing', 'missing', 'missing'])
        self.assertEqual(result.segments[1].overlap, 'missing-only')
        self.assertEqual(len(result.segments[1].sources), 2)
        self.assertEqual(result.missing_length, 4)

    def test_fractional_rates_stay_exact(self):
        self.publish('one', [('A', 1, 0, 3)])
        result = self.coverage(0, 3)
        self.assertEqual(result.total_litres, Fraction(1))
        self.assertEqual(result.segments[0].litres, Fraction(1))
        result = self.coverage(1, 2)
        self.assertEqual(result.segments[0].litres, Fraction(1, 3))

    def test_v1_rows_do_not_create_interval_categories(self):
        self.publish('legacy', [('A', 5), ('A', None)])
        result = self.coverage(0, 4)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.segments, ())
        self.assertEqual(result.uncovered_length, 0)
        self.assertEqual(result.total_litres, Fraction(0))
        self.assertEqual(self.statement().totals[0].litres, 5)

    def test_same_id_with_changed_interval_category_reading_or_order_conflicts(self):
        binding = self.stage('stable', [('A', 8, 0, 4), ('B', 2, 4, 6)])
        self.assertEqual(self.stage('stable', [('A', 8, 0, 4), ('B', 2, 4, 6)]), binding)
        for changed in (
            [('A', 8, 0, 5), ('B', 2, 4, 6)],
            [('A', 9, 0, 4), ('B', 2, 4, 6)],
            [('C', 8, 0, 4), ('B', 2, 4, 6)],
            [('B', 2, 4, 6), ('A', 8, 0, 4)],
            [('A', 8, 0, 4)],
        ):
            with self.subTest(changed=changed), self.assertRaises(SubmissionConflict):
                self.stage('stable', changed)
        other = '2026-11-22/binting'
        ensure_partition(self.database, other, ('A',))
        with self.assertRaises(SubmissionConflict):
            submit(self.database, other, 'stable', [('A', 8, 0, 4), ('B', 2, 4, 6)])

    def test_compaction_and_snapshot_preserve_exact_coverage(self):
        self.publish('sample-a', [('A', 8, 0, 4)])
        self.publish('sample-b', [('A', 8, 2, 6)])
        self.publish('unknown', [('B', None, 1, 3)])
        self.publish('zero', [('C', 0, 0, 5)])
        pin(self.database, self.partition, 'fixed')
        before_current = self.coverage(0, 6)
        before_fixed = self.coverage(0, 6, 'fixed')
        compact(self.database, self.partition, self.statement().page_ids)
        current = self.coverage(0, 6)
        fixed = self.coverage(0, 6, 'fixed')
        self.assertEqual(current, before_current)
        self.assertEqual(fixed, before_fixed)
        self.assertEqual(current.total_litres, Fraction(12))
        self.assertEqual(current.missing_length, 2)

    def test_pending_interval_page_survives_reopen_and_compaction(self):
        a = self.publish('early', [('A', 8, 0, 4)])
        binding = self.stage('late', [('A', 8, 2, 6), ('B', None, 0, 2)])
        compact(self.database, self.partition, (a.page_id,))
        initialize_store(self.database)
        self.assertEqual(self.coverage(0, 6).total_litres, Fraction(8))
        finish(self.database, binding.submission_id, binding.fingerprint)
        result = self.coverage(0, 6)
        self.assertEqual(result.total_litres, Fraction(12))
        self.assertEqual(result.missing_length, 2)

    def test_snapshot_release_and_unknown_partition_follow_v1_errors(self):
        self.publish('a', [('A', 8, 0, 4)])
        pin(self.database, self.partition, 'held')
        release(self.database, 'held')
        with self.assertRaises(LookupError):
            self.coverage(0, 4, 'held')
        with self.assertRaises(LookupError):
            read_coverage(self.database, 'missing/partition', 0, 4)
        for start, end in ((0, 0), (4, 0), (0, True), (False, 4), (0.0, 4)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                read_coverage(self.database, self.partition, start, end)

    def test_corrupt_interval_page_rejects_entire_coverage(self):
        import json

        receipt = self.publish('a', [('A', 8, 0, 4)])
        with read_transaction(self.database) as db:
            original = db.execute(
                'SELECT body FROM page_objects WHERE page_id = ?', (receipt.page_id,)
            ).fetchone()['body']
        for column, replacement in (
            ('starts', [4]), ('ends', [0]), ('starts', [True]), ('ends', [0.0]),
        ):
            with self.subTest(column=column, replacement=replacement):
                payload = json.loads(original)
                payload[column] = replacement
                with write_transaction(self.database) as db:
                    db.execute(
                        'UPDATE page_objects SET body = ? WHERE page_id = ?',
                        (json.dumps(payload), receipt.page_id),
                    )
                with self.assertRaises(PageDataError):
                    self.coverage(0, 4)

    def test_dictionary_reclaim_respects_pending_interval_pages(self):
        a = self.publish('a', [('A', 8, 0, 4)])
        binding = self.stage('pending', [('D', 3, 0, 2)])
        pin(self.database, self.partition, 'held')
        compact(self.database, self.partition, (a.page_id,))
        self.assertIn(a.dictionary_id, reclaim(self.database, self.partition).retained)
        release(self.database, 'held')
        self.assertIn(a.dictionary_id, reclaim(self.database, self.partition).reclaimed)
        self.publish('pending', [('D', 3, 0, 2)])
        self.assertEqual(self.coverage(0, 2).total_litres, Fraction(7))
