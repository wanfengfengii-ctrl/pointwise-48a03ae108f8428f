from dataclasses import dataclass

from audit.evidence import EvidenceRow, build_evidence
from audit.resolve import resolve_view
from audit.rows import load_view_rows
from audit.totals import CategoryTotal, calculate_totals
from catalog.storage import read_transaction
from pages.layout import require_name


@dataclass(frozen=True)
class Statement:
    partition: str
    snapshot_id: str | None
    page_ids: tuple[int, ...]
    totals: tuple[CategoryTotal, ...]
    evidence: tuple[EvidenceRow, ...]


def read(database, partition: str, snapshot_id: str | None = None) -> Statement:
    """Return classification totals and evidence from one complete lake view."""
    require_name(partition, 'partition')
    if snapshot_id is not None:
        require_name(snapshot_id, 'snapshot ID')
    with read_transaction(database) as db:
        view = resolve_view(db, partition, snapshot_id)
        rows = load_view_rows(db, view)
        return Statement(
            view.partition,
            view.snapshot_id,
            tuple(entry.page_id for entry in view.entries),
            calculate_totals(rows),
            build_evidence(rows),
        )
