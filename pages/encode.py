from collections.abc import Iterable
from typing import Protocol

from pages.layout import PageBody, PageDataError, SourcePosition, validate_layout


class _Observation(Protocol):
    @property
    def category(self) -> str: ...

    @property
    def reading(self) -> int | None: ...

    @property
    def source(self) -> SourcePosition: ...


def encode_rows(categories: tuple[str, ...], rows: Iterable[_Observation]) -> PageBody:
    code_for = {category: index for index, category in enumerate(categories)}
    if len(code_for) != len(categories):
        raise PageDataError('duplicate category in encoding dictionary')
    codes = []
    readings = []
    sources = []
    for row in rows:
        try:
            code = code_for[row.category]
        except KeyError as exc:
            raise PageDataError(f'category {row.category!r} is missing from the dictionary') from exc
        codes.append(code)
        readings.append(row.reading)
        sources.append(row.source)
    body = PageBody(tuple(codes), tuple(readings), tuple(sources))
    validate_layout(body)
    return body
