from dataclasses import dataclass


class PageDataError(ValueError):
    """A required page or encoding is unusable."""


def require_name(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be nonblank text')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{field} must be valid Unicode text') from exc
    return value


def is_coordinate(value) -> bool:
    """Only true integer coordinates qualify; booleans are not intervals."""
    return type(value) is int


@dataclass(frozen=True, order=True)
class SourcePosition:
    partition: str
    submission_id: str
    row_number: int


@dataclass(frozen=True)
class PageBody:
    codes: tuple[int, ...]
    readings: tuple[int | None, ...]
    sources: tuple[SourcePosition, ...]
    starts: tuple[int | None, ...] | None = None
    ends: tuple[int | None, ...] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.codes, tuple) and self.starts is None:
            object.__setattr__(self, 'starts', (None,) * len(self.codes))
        if isinstance(self.codes, tuple) and self.ends is None:
            object.__setattr__(self, 'ends', (None,) * len(self.codes))


def validate_layout(body: PageBody) -> None:
    columns = (body.codes, body.readings, body.sources, body.starts, body.ends)
    if not all(isinstance(column, tuple) for column in columns):
        raise PageDataError('page columns must be immutable sequences')
    if (
        not body.codes
        or len(body.codes) != len(body.readings)
        or len(body.codes) != len(body.sources)
        or len(body.codes) != len(body.starts)
        or len(body.codes) != len(body.ends)
    ):
        raise PageDataError('page columns must be nonempty and aligned')
    for code, reading, source, start, end in zip(
        body.codes, body.readings, body.sources, body.starts, body.ends, strict=True
    ):
        if type(code) is not int or code < 0:
            raise PageDataError('invalid category code')
        if reading is not None and type(reading) is not int:
            raise PageDataError('invalid litre reading')
        if (start is None) != (end is None):
            raise PageDataError('interval bounds must both be present or both absent')
        if start is not None:
            if not is_coordinate(start) or not is_coordinate(end):
                raise PageDataError('invalid interval bounds')
            if start >= end:
                raise PageDataError('interval start must precede its end')
        if not isinstance(source, SourcePosition):
            raise PageDataError('invalid source position')
        try:
            require_name(source.partition, 'source partition')
            require_name(source.submission_id, 'source submission ID')
        except ValueError as exc:
            raise PageDataError('invalid source position') from exc
        if type(source.row_number) is not int or source.row_number < 1:
            raise PageDataError('invalid source row number')
