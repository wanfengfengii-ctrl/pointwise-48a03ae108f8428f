from collections.abc import Iterable
from dataclasses import dataclass

from catalog.manifests import PageEntry, current_members, read_page_entry
from catalog.storage import read_transaction
from pages.dictionaries import CategoryDictionary, load_dictionary
from pages.layout import PageBody, require_name
from pages.objects import load_page


class StaleSources(LookupError):
    """At least one selected source is no longer a current member."""


@dataclass(frozen=True)
class _SourcePage:
    entry: PageEntry
    body: PageBody
    dictionary: CategoryDictionary


@dataclass(frozen=True)
class SourceSelection:
    partition: str
    sources: tuple[_SourcePage, ...]

    @property
    def source_ids(self) -> tuple[int, ...]:
        return tuple(source.entry.page_id for source in self.sources)


def select_sources(database, partition: str, source_page_ids: Iterable[int]) -> SourceSelection:
    require_name(partition, 'partition')
    try:
        selected = tuple(source_page_ids)
    except TypeError as exc:
        raise ValueError('supply a nonempty collection of source page IDs') from exc
    if not selected or any(type(page_id) is not int or page_id < 1 for page_id in selected):
        raise ValueError('supply positive integer source page IDs')
    wanted = set(selected)
    if len(wanted) != len(selected):
        raise ValueError('duplicate source page ID')

    with read_transaction(database) as db:
        members = current_members(db, partition)
        unavailable = wanted.difference(members)
        if unavailable:
            raise StaleSources(f'source pages are no longer current in {partition!r}: {sorted(unavailable)}')
        sources = []
        for page_id in members:
            if page_id in wanted:
                entry = read_page_entry(db, partition, page_id)
                body = load_page(db, page_id)
                dictionary = load_dictionary(db, partition, entry.dictionary_id)
                sources.append(_SourcePage(entry, body, dictionary))
    return SourceSelection(partition, tuple(sources))
