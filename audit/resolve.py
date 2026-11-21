from dataclasses import dataclass
import sqlite3

from catalog.manifests import PageEntry, current_members, read_page_entry
from catalog.snapshots import snapshot_members


@dataclass(frozen=True)
class ResolvedView:
    partition: str
    snapshot_id: str | None
    entries: tuple[PageEntry, ...]


def resolve_view(db: sqlite3.Connection, partition: str, snapshot_id: str | None = None) -> ResolvedView:
    if snapshot_id is None:
        members = current_members(db, partition)
    else:
        members = snapshot_members(db, partition, snapshot_id)
    entries = tuple(read_page_entry(db, partition, page_id) for page_id in members)
    return ResolvedView(partition, snapshot_id, entries)
