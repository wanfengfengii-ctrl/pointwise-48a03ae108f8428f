from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audit.statement import read
from catalog.partitions import ensure_partition
from catalog.references import dictionary_references
from catalog.storage import initialize_store, read_transaction
from intake.pending import read_pending_page
from intake.publish import finish
from intake.requests import submit
from pages.dictionaries import load_dictionary


class LakeTestCase(unittest.TestCase):
    partition = '2026-11-21/binting'

    def setUp(self):
        directory = TemporaryDirectory(prefix='binting-test-')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.database = self.directory / 'lake.sqlite3'
        initialize_store(self.database)
        self.initial_dictionary = ensure_partition(self.database, self.partition, ('B', 'A'))

    def stage(self, submission_id, rows):
        return submit(self.database, self.partition, submission_id, rows)

    def publish(self, submission_id, rows):
        binding = self.stage(submission_id, rows)
        return finish(self.database, binding.submission_id, binding.fingerprint)

    def statement(self, snapshot_id=None):
        return read(self.database, self.partition, snapshot_id)

    def pending(self, submission_id):
        with read_transaction(self.database) as db:
            return read_pending_page(db, submission_id)

    def dictionary(self, dictionary_id):
        with read_transaction(self.database) as db:
            return load_dictionary(db, self.partition, dictionary_id)

    def references(self, dictionary_id):
        with read_transaction(self.database) as db:
            return dictionary_references(db, self.partition, dictionary_id)
