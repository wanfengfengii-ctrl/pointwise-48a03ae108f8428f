from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from audit.coverage import read_coverage
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


def run_coverage_demo(database) -> None:
    """Show interval coverage cases from the handoff contract on a fresh lake."""
    sample = initialize_example(database)
    partition = sample['partition']
    for submission_id, rows in (
        ('sample-a', [('A', 8, 0, 4)]),
        ('sample-b', [('A', 8, 2, 6)]),
        ('zero-c', [('C', 0, 0, 4)]),
        ('missing-d', [('D', None, 2, 6)]),
    ):
        binding = submit(database, partition, submission_id, rows)
        finish(database, binding.submission_id, binding.fingerprint)

    def shape(statement):
        return [
            {
                'category': segment.category,
                'start': segment.start,
                'end': segment.end,
                'state': segment.state,
                'litres': None if segment.litres is None else str(segment.litres),
                'overlap': segment.overlap,
                'sources': [f'{source.submission_id}#{source.row_number}' for source in segment.sources],
            }
            for segment in statement.segments
        ]

    same_rate = read_coverage(database, partition, 1, 5)
    expected_same_rate = [
        {'category': 'A', 'start': 1, 'end': 2, 'state': 'value', 'litres': '2', 'overlap': 'none', 'sources': ['sample-a#1']},
        {'category': 'A', 'start': 2, 'end': 4, 'state': 'value', 'litres': '4', 'overlap': 'same-rate', 'sources': ['sample-a#1', 'sample-b#1']},
        {'category': 'A', 'start': 4, 'end': 5, 'state': 'value', 'litres': '2', 'overlap': 'none', 'sources': ['sample-b#1']},
        {'category': 'C', 'start': 1, 'end': 4, 'state': 'value', 'litres': '0', 'overlap': 'none', 'sources': ['zero-c#1']},
        {'category': 'C', 'start': 4, 'end': 5, 'state': 'uncovered', 'litres': None, 'overlap': 'uncovered', 'sources': []},
        {'category': 'D', 'start': 1, 'end': 2, 'state': 'uncovered', 'litres': None, 'overlap': 'uncovered', 'sources': []},
        {'category': 'D', 'start': 2, 'end': 5, 'state': 'missing', 'litres': None, 'overlap': 'missing-only', 'sources': ['missing-d#1']},
    ]
    if same_rate.status != 'ok' or shape(same_rate) != expected_same_rate:
        raise AssertionError('same-rate coverage differs from the handoff contract')
    if same_rate.total_litres != 8 or same_rate.missing_length != 3 or same_rate.uncovered_length != 2:
        raise AssertionError('coverage lengths or exact total differ from the handoff contract')

    pin(database, partition, 'before-conflict')
    conflict_binding = submit(database, partition, 'sample-conflict', [('A', 10, 2, 6)])
    finish(database, conflict_binding.submission_id, conflict_binding.fingerprint)
    conflict = read_coverage(database, partition, 1, 5)
    if (conflict.status, conflict.reason) != ('rejected', 'conflicting-overlap'):
        raise AssertionError('conflicting rate coverage was not rejected')
    if conflict.segments or conflict.total_litres != 0 or conflict.conflict is None:
        raise AssertionError('a rejected coverage query delivered partial results')

    fixed_before = read_coverage(database, partition, 1, 5, 'before-conflict')
    if fixed_before.status != 'ok' or fixed_before.total_litres != 8:
        raise AssertionError('fixed snapshot does not retain the earlier coverage facts')
    compact(database, partition, read(database, partition).page_ids)
    fixed_after = read_coverage(database, partition, 1, 5, 'before-conflict')
    current_after = read_coverage(database, partition, 1, 5)
    if shape(fixed_after) != shape(fixed_before):
        raise AssertionError('compaction changed the fixed coverage snapshot')
    if current_after.status != 'rejected' or current_after.conflict is None:
        raise AssertionError('compaction changed the conflicting current coverage verdict')

    print(json.dumps({
        'same_rate_total': str(same_rate.total_litres),
        'same_rate_segments': shape(same_rate),
        'conflict_status': conflict.status,
        'conflict_rates': [None if rate is None else str(rate) for rate in conflict.conflict.rates],
        'fixed_snapshot_total_before_compact': str(fixed_before.total_litres),
        'fixed_snapshot_total_after_compact': str(fixed_after.total_litres),
        'current_after_compact': current_after.status,
    }, sort_keys=True))


if __name__ == '__main__':
    with TemporaryDirectory(prefix='binting-demo-') as directory:
        run_demo(Path(directory) / 'observations.sqlite3')
        run_coverage_demo(Path(directory) / 'coverage.sqlite3')
