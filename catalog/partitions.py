from collections.abc import Sequence
import sqlite3

from catalog.storage import write_transaction
from pages.dictionaries import CategoryDictionary, create_dictionary, load_dictionary
from pages.layout import require_name


def ensure_partition(database, partition: str, initial_categories: Sequence[str]) -> int:
    """Create a missing partition and return the current write dictionary ID."""
    require_name(partition, 'partition')
    with write_transaction(database) as db:
        row = db.execute(
            'SELECT active_dictionary_id FROM partitions WHERE name = ?', (partition,)
        ).fetchone()
        if row is not None:
            return row['active_dictionary_id']
        db.execute('INSERT INTO partitions (name) VALUES (?)', (partition,))
        dictionary = create_dictionary(db, partition, initial_categories)
        activate_dictionary(db, dictionary)
        return dictionary.dictionary_id


def _active_id(db: sqlite3.Connection, partition: str) -> int | None:
    row = db.execute('SELECT active_dictionary_id FROM partitions WHERE name = ?', (partition,)).fetchone()
    if row is None:
        raise LookupError(f'unknown partition {partition!r}')
    return row['active_dictionary_id']


def active_dictionary(db: sqlite3.Connection, partition: str) -> CategoryDictionary:
    return load_dictionary(db, partition, _active_id(db, partition))


def activate_dictionary(db: sqlite3.Connection, dictionary: CategoryDictionary) -> None:
    partition = dictionary.partition
    next_id = dictionary.dictionary_id
    previous_id = _active_id(db, partition)
    if previous_id == next_id:
        return
    db.execute('UPDATE partitions SET active_dictionary_id = ? WHERE name = ?', (next_id, partition))
    forget_retired_dictionary(db, partition, next_id)
    if previous_id is not None:
        db.execute(
            'INSERT INTO retired_dictionaries (partition, dictionary_id) VALUES (?, ?)',
            (partition, previous_id),
        )


def retired_dictionaries(db: sqlite3.Connection, partition: str) -> tuple[int, ...]:
    current_id = _active_id(db, partition)
    rows = db.execute(
        'SELECT dictionary_id FROM retired_dictionaries '
        'WHERE partition = ? AND dictionary_id <> ? ORDER BY dictionary_id',
        (partition, current_id),
    )
    return tuple(row['dictionary_id'] for row in rows)


def forget_retired_dictionary(db: sqlite3.Connection, partition: str, dictionary_id: int) -> None:
    db.execute(
        'DELETE FROM retired_dictionaries WHERE partition = ? AND dictionary_id = ?',
        (partition, dictionary_id),
    )
