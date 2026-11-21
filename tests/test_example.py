from audit.evidence import EvidenceRow
from audit.statement import read
from audit.totals import CategoryTotal
from catalog.partitions import active_dictionary
from catalog.snapshots import pin
from catalog.storage import read_transaction
from demo import initialize_example, run_demo
from intake.publish import finish
from intake.requests import submit
from pages.layout import SourcePosition
from tests.support import LakeTestCase


class ExampleTests(LakeTestCase):
    def test_example_runs_persistent_day_and_handover(self):
        database = self.directory / 'fresh-example.sqlite3'
        run_demo(database)
        statement = read(database, self.partition)
        self.assertEqual(statement.totals, (CategoryTotal('A', 2, 1, 5), CategoryTotal('B', 1, 0, 7)))
        self.assertEqual(statement.evidence[-1], EvidenceRow(SourcePosition(self.partition, 'station-b', 1), 'B', 7))
        with self.assertRaises(LookupError):
            read(database, self.partition, 'morning')

    def test_repeated_initialization_preserves_written_partition_and_pending_work(self):
        database = self.directory / 'reinitialized.sqlite3'
        sample = initialize_example(database)
        partition = sample['partition']
        binding = submit(database, partition, 'operator-report', [(' C ', 12)])
        receipt = finish(database, binding.submission_id, binding.fingerprint)
        pin(database, partition, 'operator-review')
        pending = submit(database, partition, 'still-pending', [('D', 3)])
        with read_transaction(database) as db:
            expanded = active_dictionary(db, partition)
        self.assertEqual(expanded.categories, ('B', 'A', 'C', 'D'))

        self.assertEqual(initialize_example(database), sample)
        self.assertEqual(initialize_example(database), sample)
        with read_transaction(database) as db:
            self.assertEqual(active_dictionary(db, partition), expanded)
        self.assertEqual(finish(database, binding.submission_id, binding.fingerprint), receipt)
        held = read(database, partition, 'operator-review')
        self.assertEqual(held.page_ids, (receipt.page_id,))
        self.assertEqual(held.totals, (CategoryTotal('C', 1, 0, 12),))
        self.assertEqual(held.evidence, (EvidenceRow(SourcePosition(partition, 'operator-report', 1), 'C', 12),))
        self.assertEqual(read(database, partition).page_ids, (receipt.page_id,))
        finish(database, pending.submission_id, pending.fingerprint)
        self.assertEqual(read(database, partition).totals, (
            CategoryTotal('C', 1, 0, 12), CategoryTotal('D', 1, 0, 3),
        ))
