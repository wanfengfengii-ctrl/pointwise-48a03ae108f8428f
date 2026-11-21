from audit.totals import CategoryTotal
from catalog.partitions import retired_dictionaries
from catalog.snapshots import pin, release
from catalog.storage import StorageFailure, initialize_store, read_transaction, write_transaction
from intake.publish import finish
from intake.requests import submit
from maintenance.compact import compact
from maintenance.reclaim import ReclaimResult, reclaim
from pages.layout import PageDataError
from tests.support import LakeTestCase


class ReclaimTests(LakeTestCase):
    def test_snapshot_alone_keeps_old_dictionary_until_released(self):
        a = self.publish('early', [('A', 5)])
        old_id = a.dictionary_id
        pin(self.database, self.partition, 'old')
        replacement = compact(self.database, self.partition, (a.page_id,))
        refs = self.references(old_id)
        self.assertEqual(refs.current_pages, ())
        self.assertEqual(refs.pending_submissions, ())
        self.assertEqual(refs.snapshot_pages, (('old', a.page_id),))
        self.assertEqual(reclaim(self.database, self.partition), ReclaimResult((), (old_id,)))
        self.assertEqual(self.statement('old').totals, (CategoryTotal('A', 1, 0, 5),))
        release(self.database, 'old')
        with self.assertRaises(LookupError):
            self.statement('old')
        with self.assertRaises(LookupError):
            release(self.database, 'old')
        self.assertEqual(reclaim(self.database, self.partition), ReclaimResult((old_id,), ()))
        with self.assertRaises(PageDataError):
            self.dictionary(old_id)
        self.assertEqual(self.statement().page_ids, (replacement.page_id,))
        self.assertEqual(self.statement().totals, (CategoryTotal('A', 1, 0, 5),))
        binding = self.stage('early', [('A', 5)])
        self.assertEqual(finish(self.database, 'early', binding.fingerprint), a)
        self.assertEqual(reclaim(self.database, self.partition), ReclaimResult((), ()))

    def test_pending_then_current_page_keeps_dictionary_until_rewrite(self):
        a = self.publish('early', [('A', 5)])
        old_id = a.dictionary_id
        pin(self.database, self.partition, 'old')
        b = self.stage('pending', [('B', 7)])
        compact(self.database, self.partition, (a.page_id,))
        refs_with_both = self.references(old_id)
        self.assertEqual(refs_with_both.snapshot_pages, (('old', a.page_id),))
        self.assertEqual(refs_with_both.pending_submissions, ('pending',))
        self.assertEqual(reclaim(self.database, self.partition), ReclaimResult((), (old_id,)))
        self.assertEqual(self.statement('old').totals, (CategoryTotal('A', 1, 0, 5),))
        release(self.database, 'old')
        refs_pending = self.references(old_id)
        self.assertEqual(refs_pending.snapshot_pages, ())
        self.assertEqual(refs_pending.current_pages, ())
        self.assertEqual(refs_pending.pending_submissions, ('pending',))
        self.assertEqual(reclaim(self.database, self.partition), ReclaimResult((), (old_id,)))
        self.assertEqual(self.dictionary(old_id).categories, ('B', 'A'))
        initialize_store(self.database)
        b_receipt = finish(self.database, b.submission_id, b.fingerprint)
        refs_current = self.references(old_id)
        self.assertEqual(refs_current.current_pages, (b_receipt.page_id,))
        self.assertEqual(refs_current.pending_submissions, ())
        self.assertEqual(reclaim(self.database, self.partition), ReclaimResult((), (old_id,)))
        compact(self.database, self.partition, (b_receipt.page_id,))
        self.assertFalse(self.references(old_id).needed)
        self.assertIn(old_id, reclaim(self.database, self.partition).reclaimed)
        with self.assertRaises(PageDataError):
            self.dictionary(old_id)
        self.assertEqual(self.statement().totals, (CategoryTotal('A', 1, 0, 5), CategoryTotal('B', 1, 0, 7)))
        self.assertEqual(finish(self.database, b.submission_id, b.fingerprint), b_receipt)

    def test_failed_object_delete_rolls_back_the_whole_reclaim(self):
        a = self.publish('early', [('A', 5)])
        first = compact(self.database, self.partition, (a.page_id,))
        final = compact(self.database, self.partition, (first.page_id,))
        blocked = first.dictionary_id
        with write_transaction(self.database) as db:
            db.execute('CREATE TABLE test_delete_block (dictionary_id INTEGER PRIMARY KEY)')
            db.execute('INSERT INTO test_delete_block VALUES (?)', (blocked,))
            db.execute('''
                CREATE TRIGGER test_reject_dictionary_delete BEFORE DELETE ON dictionaries
                WHEN EXISTS (SELECT 1 FROM test_delete_block WHERE dictionary_id = OLD.dictionary_id)
                BEGIN SELECT RAISE(ABORT, 'dictionary delete blocked'); END
            ''')
        with self.assertRaises(StorageFailure) as failure:
            reclaim(self.database, self.partition)
        self.assertIn('dictionary delete blocked', str(failure.exception.__cause__))
        initialize_store(self.database)
        retired = (a.dictionary_id, blocked)
        with read_transaction(self.database) as db:
            self.assertEqual(retired_dictionaries(db, self.partition), retired)
        self.assertEqual(self.dictionary(a.dictionary_id).categories, ('B', 'A'))
        self.assertEqual(self.dictionary(blocked).categories, ('A',))
        with write_transaction(self.database) as db:
            db.execute('DROP TRIGGER test_reject_dictionary_delete')
            db.execute('DROP TABLE test_delete_block')
        self.assertEqual(reclaim(self.database, self.partition), ReclaimResult(retired, ()))
        for dictionary_id in retired:
            with self.assertRaises(PageDataError):
                self.dictionary(dictionary_id)
        self.assertEqual(self.statement().page_ids, (final.page_id,))
        self.assertEqual(self.statement().totals, (CategoryTotal('A', 1, 0, 5),))
