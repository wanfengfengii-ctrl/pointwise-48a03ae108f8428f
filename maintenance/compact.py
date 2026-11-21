from collections.abc import Callable, Iterable

from catalog.manifests import PageEntry
from maintenance.install import install_rewrite
from maintenance.rewrite import build_rewrite
from maintenance.select import SourceSelection, select_sources


def compact(
    database,
    partition: str,
    source_page_ids: Iterable[int],
    *,
    after_select: Callable[[SourceSelection], None] | None = None,
) -> PageEntry:
    """Rewrite selected current pages and atomically install their replacement."""
    selection = select_sources(database, partition, source_page_ids)
    if after_select is not None:
        after_select(selection)
    candidate = build_rewrite(selection)
    return install_rewrite(database, candidate)
