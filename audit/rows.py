import sqlite3

from audit.resolve import ResolvedView
from pages.decode import DecodedRow, decode_page
from pages.dictionaries import load_dictionary
from pages.objects import load_page


def load_view_rows(db: sqlite3.Connection, view: ResolvedView) -> tuple[DecodedRow, ...]:
    rows = []
    for entry in view.entries:
        body = load_page(db, entry.page_id)
        dictionary = load_dictionary(db, view.partition, entry.dictionary_id)
        rows.extend(decode_page(body, dictionary))
    return tuple(rows)
