from dataclasses import dataclass
import sqlite3

from pages.layout import PageDataError


@dataclass(frozen=True)
class PageEntry:
    page_id: int
    partition: str
    dictionary_id: int


def register_page(db: sqlite3.Connection, page_id: int, partition: str, dictionary_id: int) -> PageEntry:
    db.execute(
        'INSERT INTO page_entries (page_id, partition, dictionary_id) VALUES (?, ?, ?)',
        (page_id, partition, dictionary_id),
    )
    return PageEntry(page_id, partition, dictionary_id)


def read_page_entry(db: sqlite3.Connection, partition: str, page_id: int) -> PageEntry:
    row = db.execute(
        'SELECT dictionary_id FROM page_entries WHERE partition = ? AND page_id = ?',
        (partition, page_id),
    ).fetchone()
    if row is None:
        raise PageDataError(f'page {page_id} does not have a registration in {partition!r}')
    return PageEntry(page_id, partition, row['dictionary_id'])


def current_members(db: sqlite3.Connection, partition: str) -> tuple[int, ...]:
    rows = db.execute(
        'SELECT members.page_id FROM partitions '
        'LEFT JOIN current_members AS members ON members.partition = partitions.name '
        'WHERE partitions.name = ? ORDER BY members.ordinal',
        (partition,),
    ).fetchall()
    if not rows:
        raise LookupError(f'unknown partition {partition!r}')
    return tuple(row['page_id'] for row in rows if row['page_id'] is not None)


def append_member(db: sqlite3.Connection, entry: PageEntry) -> None:
    db.execute(
        'INSERT INTO current_members (partition, ordinal, page_id) '
        'SELECT ?, COALESCE(MAX(ordinal), -1) + 1, ? '
        'FROM current_members WHERE partition = ?',
        (entry.partition, entry.page_id, entry.partition),
    )


def write_members(db: sqlite3.Connection, partition: str, page_ids: tuple[int, ...]) -> None:
    """Persist the ordered members chosen by the caller's write transaction."""
    db.execute('DELETE FROM current_members WHERE partition = ?', (partition,))
    db.executemany(
        'INSERT INTO current_members (partition, ordinal, page_id) VALUES (?, ?, ?)',
        ((partition, ordinal, page_id) for ordinal, page_id in enumerate(page_ids)),
    )
