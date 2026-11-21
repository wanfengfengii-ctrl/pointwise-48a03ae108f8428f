from catalog.manifests import PageEntry, current_members, register_page, write_members
from catalog.partitions import activate_dictionary
from catalog.storage import write_transaction
from maintenance.rewrite import RewriteCandidate
from maintenance.select import StaleSources
from pages.dictionaries import create_dictionary
from pages.objects import store_page


def _replace_sources(
    members: tuple[int, ...], sources: set[int], replacement: int
) -> tuple[int, ...]:
    position = next(page_id for page_id in members if page_id in sources)
    return tuple(
        replacement if page_id == position else page_id
        for page_id in members
        if page_id == position or page_id not in sources
    )


def install_rewrite(database, candidate: RewriteCandidate) -> PageEntry:
    partition = candidate.partition
    sources = set(candidate.source_ids)
    if not sources or len(sources) != len(candidate.source_ids):
        raise ValueError('rewrite requires a nonempty set of distinct sources')
    with write_transaction(database) as db:
        members = current_members(db, partition)
        unavailable = sources.difference(members)
        if unavailable:
            raise StaleSources(f'source pages lost replacement eligibility: {sorted(unavailable)}')
        dictionary = create_dictionary(db, partition, candidate.categories)
        page_id = store_page(db, candidate.body)
        entry = register_page(db, page_id, partition, dictionary.dictionary_id)
        write_members(db, partition, _replace_sources(members, sources, page_id))
        activate_dictionary(db, dictionary)
        return entry
