from dataclasses import dataclass

from pages.dictionaries import CategoryDictionary
from pages.layout import PageBody, PageDataError, SourcePosition, validate_layout


@dataclass(frozen=True)
class DecodedRow:
    category: str
    reading: int | None
    source: SourcePosition


def decode_page(body: PageBody, dictionary: CategoryDictionary) -> tuple[DecodedRow, ...]:
    validate_layout(body)
    rows = []
    for code, reading, source in zip(body.codes, body.readings, body.sources, strict=True):
        if code >= len(dictionary.categories):
            raise PageDataError(f'code {code} outside dictionary {dictionary.dictionary_id}')
        if source.partition != dictionary.partition:
            raise PageDataError('source and dictionary partitions disagree')
        rows.append(DecodedRow(dictionary.categories[code], reading, source))
    return tuple(rows)
