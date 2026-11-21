from dataclasses import dataclass

from catalog.partitions import forget_retired_dictionary, retired_dictionaries
from catalog.references import dictionary_references
from catalog.storage import write_transaction
from pages.dictionaries import delete_dictionary
from pages.layout import require_name


@dataclass(frozen=True)
class ReclaimResult:
    reclaimed: tuple[int, ...]
    retained: tuple[int, ...]


def reclaim(database, partition: str) -> ReclaimResult:
    require_name(partition, 'partition')
    reclaimed = []
    retained = []
    with write_transaction(database) as db:
        for dictionary_id in retired_dictionaries(db, partition):
            references = dictionary_references(db, partition, dictionary_id)
            if references.needed:
                retained.append(dictionary_id)
            else:
                forget_retired_dictionary(db, partition, dictionary_id)
                delete_dictionary(db, partition, dictionary_id)
                reclaimed.append(dictionary_id)
    return ReclaimResult(tuple(reclaimed), tuple(retained))
