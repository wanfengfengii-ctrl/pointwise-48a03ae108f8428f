from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class DictionaryReferences:
    current_pages: tuple[int, ...]
    snapshot_pages: tuple[tuple[str, int], ...]
    pending_submissions: tuple[str, ...]

    @property
    def needed(self) -> bool:
        return bool(self.current_pages or self.snapshot_pages or self.pending_submissions)


def dictionary_references(db: sqlite3.Connection, partition: str, dictionary_id: int) -> DictionaryReferences:
    key = (partition, dictionary_id)
    current = db.execute(
        'SELECT members.page_id FROM current_members AS members '
        'JOIN page_entries AS pages USING (page_id) '
        'WHERE members.partition = ? AND pages.dictionary_id = ? ORDER BY members.ordinal', key,
    )
    snapshots = db.execute(
        'SELECT held.snapshot_id, members.page_id FROM snapshots AS held '
        'JOIN snapshot_members AS members USING (snapshot_id) '
        'JOIN page_entries AS pages USING (page_id) '
        'WHERE held.partition = ? AND pages.dictionary_id = ? '
        'ORDER BY held.snapshot_id, members.ordinal', key,
    )
    pending = db.execute(
        'SELECT pending.submission_id FROM pending_pages AS pending '
        'JOIN submissions AS incoming USING (submission_id) '
        'WHERE incoming.partition = ? AND pending.dictionary_id = ? ORDER BY pending.submission_id', key,
    )
    return DictionaryReferences(
        tuple(row['page_id'] for row in current),
        tuple((row['snapshot_id'], row['page_id']) for row in snapshots),
        tuple(row['submission_id'] for row in pending),
    )
