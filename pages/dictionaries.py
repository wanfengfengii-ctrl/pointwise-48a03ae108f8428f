from collections.abc import Iterable
from dataclasses import dataclass
from itertools import chain
import json
import sqlite3

from pages.layout import PageDataError, require_name


@dataclass(frozen=True)
class CategoryDictionary:
    dictionary_id: int
    partition: str
    categories: tuple[str, ...]


def _validate_categories(categories: tuple[str, ...]) -> None:
    for category in categories:
        require_name(category, 'category')
        if category != category.strip():
            raise ValueError('dictionary categories must be normalized')
    if len(set(categories)) != len(categories):
        raise ValueError('dictionary categories must be distinct')


def create_dictionary(
    db: sqlite3.Connection, partition: str, categories: Iterable[str]
) -> CategoryDictionary:
    if isinstance(categories, (str, bytes)):
        raise ValueError('dictionary categories must be a sequence of names')
    try:
        entries = tuple(categories)
    except TypeError as exc:
        raise ValueError('dictionary categories must be iterable') from exc
    _validate_categories(entries)
    cursor = db.execute(
        'INSERT INTO dictionaries (partition, categories) VALUES (?, ?)',
        (partition, json.dumps(entries, separators=(',', ':'))),
    )
    return CategoryDictionary(cursor.lastrowid, partition, entries)


def load_dictionary(db: sqlite3.Connection, partition: str, dictionary_id: int) -> CategoryDictionary:
    row = db.execute(
        'SELECT categories FROM dictionaries WHERE partition = ? AND dictionary_id = ?',
        (partition, dictionary_id),
    ).fetchone()
    if row is None:
        raise PageDataError(f'dictionary {dictionary_id} is unavailable for {partition!r}')
    try:
        payload = json.loads(row['categories'])
        if not isinstance(payload, list):
            raise ValueError('dictionary payload must be a list')
        categories = tuple(payload)
        _validate_categories(categories)
    except (ValueError, TypeError, RecursionError) as exc:
        raise PageDataError(f'invalid dictionary {dictionary_id}') from exc
    return CategoryDictionary(dictionary_id, partition, categories)


def extend_categories(dictionary: CategoryDictionary, observed: Iterable[str]) -> tuple[str, ...]:
    """Preserve existing codes and append new categories in occurrence order."""
    return tuple(dict.fromkeys(chain(dictionary.categories, observed)))


def delete_dictionary(db: sqlite3.Connection, partition: str, dictionary_id: int) -> None:
    cursor = db.execute(
        'DELETE FROM dictionaries WHERE partition = ? AND dictionary_id = ?',
        (partition, dictionary_id),
    )
    if cursor.rowcount != 1:
        raise PageDataError(f'dictionary {dictionary_id} could not be deleted')
