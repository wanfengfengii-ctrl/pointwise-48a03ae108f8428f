from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audit.coverage import read_coverage
from audit.statement import read
from catalog.partitions import ensure_partition
from catalog.snapshots import pin
from catalog.storage import initialize_store
from intake.publish import finish
from intake.requests import SubmissionConflict, submit
from maintenance.compact import compact


PARTITION = '2026-11-21/binting'


class CoverageVerification(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='coverage-verify-')
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'lake.sqlite3'
        initialize_store(self.database)
        ensure_partition(self.database, PARTITION, ('B', 'A'))

    def publish(self, submission_id, rows):
        binding = submit(self.database, PARTITION, submission_id, rows)
        return finish(self.database, binding.submission_id, binding.fingerprint)

    @staticmethod
    def shape(statement):
        return [
            (
                segment.category,
                segment.start,
                segment.end,
                segment.state,
                None if segment.litres is None else str(segment.litres),
                segment.overlap,
                len(segment.sources),
            )
            for segment in statement.segments
        ]

    def test_same_rate_overlap_is_counted_once_with_both_sources(self):
        self.publish('sample-a', [('A', 8, 0, 4)])
        self.publish('sample-b', [('A', 8, 2, 6)])
        result = read_coverage(self.database, PARTITION, 1, 5)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.total_litres, Fraction(8))
        self.assertEqual(self.shape(result), [
            ('A', 1, 2, 'value', '2', 'none', 1),
            ('A', 2, 4, 'value', '4', 'same-rate', 2),
            ('A', 4, 5, 'value', '2', 'none', 1),
        ])

    def test_conflicting_overlap_rejects_without_mutating_the_lake(self):
        self.publish('sample-a', [('A', 8, 0, 4)])
        self.publish('sample-b', [('A', 10, 2, 6)])
        before = read(self.database, PARTITION).page_ids
        result = read_coverage(self.database, PARTITION, 1, 5)
        self.assertEqual(result.status, 'rejected')
        self.assertEqual(result.reason, 'conflicting-overlap')
        self.assertEqual(result.segments, ())
        self.assertEqual(result.total_litres, Fraction(0))
        self.assertEqual(read(self.database, PARTITION).page_ids, before)

    def test_zero_missing_and_uncovered_are_distinct(self):
        self.publish('zero-c', [('C', 0, 0, 4)])
        self.publish('missing-d', [('D', None, 2, 6)])
        result = read_coverage(self.database, PARTITION, 1, 5)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.total_litres, Fraction(0))
        self.assertEqual(result.missing_length, 3)
        self.assertEqual(result.uncovered_length, 2)
        self.assertEqual(self.shape(result), [
            ('C', 1, 4, 'value', '0', 'none', 1),
            ('C', 4, 5, 'uncovered', None, 'uncovered', 0),
            ('D', 1, 2, 'uncovered', None, 'uncovered', 0),
            ('D', 2, 5, 'missing', None, 'missing-only', 1),
        ])

    def test_pending_reopen_and_same_id_changed_interval(self):
        binding = submit(self.database, PARTITION, 'late', [('A', 8, 0, 4)])
        initialize_store(self.database)
        finish(self.database, binding.submission_id, binding.fingerprint)
        with self.assertRaises(SubmissionConflict):
            submit(self.database, PARTITION, 'late', [('A', 8, 4, 8)])
        result = read_coverage(self.database, PARTITION, 0, 8)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.total_litres, Fraction(8))

    def test_compaction_snapshot_and_reopen_preserve_coverage(self):
        self.publish('sample-a', [('A', 8, 0, 4)])
        self.publish('sample-b', [('A', 8, 2, 6)])
        source_ids = read(self.database, PARTITION).page_ids
        pin(self.database, PARTITION, 'before-compact')
        fixed_before = read_coverage(self.database, PARTITION, 1, 5, 'before-compact')
        compact(self.database, PARTITION, source_ids)
        initialize_store(self.database)
        current_after = read_coverage(self.database, PARTITION, 1, 5)
        fixed_after = read_coverage(self.database, PARTITION, 1, 5, 'before-compact')
        self.assertEqual(self.shape(current_after), self.shape(fixed_before))
        self.assertEqual(self.shape(fixed_after), self.shape(fixed_before))
        self.assertEqual(current_after.total_litres, Fraction(8))
        self.assertEqual(fixed_after.total_litres, Fraction(8))


if __name__ == '__main__':
    unittest.main(verbosity=2)
