from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3


class StorageFailure(RuntimeError):
    """A SQLite operation could not be completed."""


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS partitions (
    name TEXT PRIMARY KEY,
    active_dictionary_id INTEGER REFERENCES dictionaries(dictionary_id)
);
CREATE TABLE IF NOT EXISTS dictionaries (
    dictionary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    partition TEXT NOT NULL REFERENCES partitions(name),
    categories TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retired_dictionaries (
    partition TEXT NOT NULL REFERENCES partitions(name),
    dictionary_id INTEGER NOT NULL REFERENCES dictionaries(dictionary_id),
    PRIMARY KEY (partition, dictionary_id)
);
CREATE TABLE IF NOT EXISTS page_objects (
    page_id INTEGER PRIMARY KEY AUTOINCREMENT,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    partition TEXT NOT NULL REFERENCES partitions(name),
    fingerprint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_pages (
    submission_id TEXT PRIMARY KEY REFERENCES submissions(submission_id),
    page_id INTEGER NOT NULL UNIQUE REFERENCES page_objects(page_id),
    dictionary_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS page_entries (
    page_id INTEGER PRIMARY KEY REFERENCES page_objects(page_id),
    partition TEXT NOT NULL REFERENCES partitions(name),
    dictionary_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS current_members (
    partition TEXT NOT NULL REFERENCES partitions(name),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    page_id INTEGER NOT NULL REFERENCES page_entries(page_id),
    PRIMARY KEY (partition, ordinal),
    UNIQUE (partition, page_id)
);
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    partition TEXT NOT NULL REFERENCES partitions(name)
);
CREATE TABLE IF NOT EXISTS snapshot_members (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    page_id INTEGER NOT NULL REFERENCES page_entries(page_id),
    PRIMARY KEY (snapshot_id, ordinal),
    UNIQUE (snapshot_id, page_id)
);
CREATE TABLE IF NOT EXISTS receipts (
    submission_id TEXT PRIMARY KEY REFERENCES submissions(submission_id),
    page_id INTEGER NOT NULL UNIQUE REFERENCES page_entries(page_id)
);
'''


def _connect(database, mode: str) -> sqlite3.Connection:
    uri = Path(database).absolute().as_uri() + '?mode=' + mode
    try:
        db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)
    except sqlite3.Error as exc:
        raise StorageFailure('could not open observation lake') from exc
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
    except sqlite3.Error as exc:
        db.close()
        raise StorageFailure('could not configure observation lake') from exc
    return db


def initialize_store(database) -> None:
    """Create missing lake tables in a persistent database."""
    with closing(_connect(database, 'rwc')) as db:
        try:
            db.execute('PRAGMA journal_mode = WAL').fetchone()
            db.executescript('BEGIN IMMEDIATE;\n' + _SCHEMA + '\nCOMMIT;')
        except sqlite3.Error as exc:
            db.rollback()
            raise StorageFailure('could not initialize observation lake') from exc


def open_store(database) -> sqlite3.Connection:
    """Open an existing lake. The caller owns the returned connection."""
    return _connect(database, 'rw')


@contextmanager
def _transaction(database, begin: str):
    with closing(open_store(database)) as db:
        try:
            db.execute(begin)
            yield db
            db.commit()
        except BaseException as exc:
            if db.in_transaction:
                db.rollback()
            if isinstance(exc, sqlite3.Error):
                raise StorageFailure('observation lake transaction failed') from exc
            raise


def read_transaction(database):
    """Use one SQLite read view for all queries in the context."""
    return _transaction(database, 'BEGIN')


def write_transaction(database):
    """Serialize state transitions and commit them on successful exit."""
    return _transaction(database, 'BEGIN IMMEDIATE')
