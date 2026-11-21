import sqlite3

from catalog.manifests import current_members
from catalog.storage import write_transaction
from pages.layout import require_name


def pin(database, partition: str, snapshot_id: str) -> tuple[int, ...]:
    require_name(partition, 'partition')
    require_name(snapshot_id, 'snapshot ID')
    with write_transaction(database) as db:
        members = current_members(db, partition)
        exists = db.execute('SELECT 1 FROM snapshots WHERE snapshot_id = ?', (snapshot_id,)).fetchone()
        if exists is not None:
            raise ValueError(f'snapshot {snapshot_id!r} is already held')
        db.execute('INSERT INTO snapshots (snapshot_id, partition) VALUES (?, ?)', (snapshot_id, partition))
        db.executemany(
            'INSERT INTO snapshot_members (snapshot_id, ordinal, page_id) VALUES (?, ?, ?)',
            ((snapshot_id, ordinal, page_id) for ordinal, page_id in enumerate(members)),
        )
        return members


def release(database, snapshot_id: str) -> None:
    require_name(snapshot_id, 'snapshot ID')
    with write_transaction(database) as db:
        cursor = db.execute('DELETE FROM snapshots WHERE snapshot_id = ?', (snapshot_id,))
        if cursor.rowcount != 1:
            raise LookupError(f'unknown snapshot {snapshot_id!r}')


def snapshot_members(db: sqlite3.Connection, partition: str, snapshot_id: str) -> tuple[int, ...]:
    exists = db.execute(
        'SELECT 1 FROM snapshots WHERE snapshot_id = ? AND partition = ?', (snapshot_id, partition)
    ).fetchone()
    if exists is None:
        raise LookupError(f'unknown snapshot {snapshot_id!r} in {partition!r}')
    rows = db.execute(
        'SELECT page_id FROM snapshot_members WHERE snapshot_id = ? ORDER BY ordinal', (snapshot_id,)
    )
    return tuple(row['page_id'] for row in rows)
