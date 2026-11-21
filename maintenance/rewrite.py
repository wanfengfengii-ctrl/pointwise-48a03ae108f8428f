from dataclasses import dataclass

from maintenance.select import SourceSelection
from pages.decode import decode_page
from pages.encode import encode_rows
from pages.layout import PageBody


@dataclass(frozen=True)
class RewriteCandidate:
    partition: str
    source_ids: tuple[int, ...]
    categories: tuple[str, ...]
    body: PageBody


def build_rewrite(selection: SourceSelection) -> RewriteCandidate:
    rows = tuple(
        row
        for source in selection.sources
        for row in decode_page(source.body, source.dictionary)
    )
    categories = tuple(dict.fromkeys(row.category for row in rows))
    body = encode_rows(categories, rows)
    return RewriteCandidate(selection.partition, selection.source_ids, categories, body)
