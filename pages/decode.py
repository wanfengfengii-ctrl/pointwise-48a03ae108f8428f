from dataclasses import dataclass

from pages.dictionaries import CategoryDictionary
from pages.layout import PageBody, PageDataError, SourcePosition, validate_layout


@dataclass(frozen=True)
class DecodedRow:
    category: str
    reading: int | None
    source: SourcePosition
    start: int | None = None
    end: int | None = None

    @property
    def has_interval(self) -> bool:
        return self.start is not None and self.end is not None


def decode_page(body: PageBody, dictionary: CategoryDictionary) -> tuple[DecodedRow, ...]:
    validate_layout(body)
    starts = body.starts if body.starts is not None else (None,) * len(body.codes)
    ends = body.ends if body.ends is not None else (None,) * len(body.codes)
    rows = []
    for code, reading, source, start, end in zip(
        body.codes, body.readings, body.sources, starts, ends, strict=True
    ):
        if code >= len(dictionary.categories):
            raise PageDataError(f'code {code} outside dictionary {dictionary.dictionary_id}')
        if source.partition != dictionary.partition:
            raise PageDataError('source and dictionary partitions disagree')
        rows.append(DecodedRow(dictionary.categories[code], reading, source, start, end))
    return tuple(rows)
