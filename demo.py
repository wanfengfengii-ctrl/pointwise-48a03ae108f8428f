from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from audit.statement import read
from catalog.partitions import ensure_partition
from catalog.snapshots import pin, release
from catalog.storage import initialize_store
from intake.publish import finish
from intake.requests import submit
from maintenance.compact import compact
from maintenance.reclaim import reclaim


def initialize_example(database) -> dict:
    fixture = Path(__file__).with_name('observations.json')
    sample = json.loads(fixture.read_text(encoding='utf-8'))
    initialize_store(database)
    ensure_partition(database, sample['partition'], sample['initial_categories'])
    return sample


def run_demo(database) -> None:
    sample = initialize_example(database)
    partition = sample['partition']
    first, second = sample['submissions']
    bound_a = submit(database, partition, first['id'], first['rows'])
    a = finish(database, bound_a.submission_id, bound_a.fingerprint)
    pin(database, partition, 'morning')
    bound_b = submit(database, partition, second['id'], second['rows'])
    compact(database, partition, (a.page_id,))
    b = finish(database, bound_b.submission_id, bound_b.fingerprint)
    before_release = reclaim(database, partition)
    held = read(database, partition, 'morning')
    release(database, 'morning')
    compact(database, partition, (b.page_id,))
    cleanup = reclaim(database, partition)
    final = read(database, partition)

    totals = [asdict(total) for total in final.totals]
    expected_totals = [
        {'category': 'A', 'row_count': 2, 'missing_count': 1, 'litres': 5},
        {'category': 'B', 'row_count': 1, 'missing_count': 0, 'litres': 7},
    ]
    evidence = [[row.source.submission_id, row.source.row_number, row.category, row.reading] for row in final.evidence]
    expected_evidence = [['station-a', 1, 'A', 5], ['station-a', 2, 'A', None], ['station-b', 1, 'B', 7]]
    if totals != expected_totals or evidence != expected_evidence:
        raise AssertionError('demo statement differs from the source observations')
    if [asdict(total) for total in held.totals] != expected_totals[:1] or held.page_ids != (a.page_id,):
        raise AssertionError('morning snapshot differs from the original A page')
    if a.dictionary_id not in before_release.retained or a.dictionary_id not in cleanup.reclaimed:
        raise AssertionError('dictionary lifetime differs from the actual page dependencies')
    if finish(database, bound_b.submission_id, bound_b.fingerprint) != b:
        raise AssertionError('receipt changed after compaction')

    scenario = {
        'case_id': 'v1',
        'input': sample,
        'expected': expected_totals,
        'actual': totals,
        'downstream_expected': expected_evidence,
        'downstream_actual': evidence,
        'code_paths': ['intake/requests.py', 'intake/publish.py', 'audit/statement.py', 'audit/totals.py', 'audit/evidence.py'],
        'oracle': 'Count A=5 and A missing as two rows and B=7 as one row. Read each original line from the sample.',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, separators=(',', ':')))
    print(json.dumps({
        'morning_totals': [asdict(row) for row in held.totals],
        'retained_before_release': before_release.retained,
        'reclaimed_after_rewrite': cleanup.reclaimed,
        'original_receipt': asdict(b),
        'current_page_ids': final.page_ids,
    }, sort_keys=True))


if __name__ == '__main__':
    with TemporaryDirectory(prefix='binting-demo-') as directory:
        run_demo(Path(directory) / 'observations.sqlite3')
