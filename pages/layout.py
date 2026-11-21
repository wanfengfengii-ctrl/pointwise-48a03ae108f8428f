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


def validate_layout(body: PageBody) -> None:
    if not all(isinstance(column, tuple) for column in (body.codes, body.readings, body.sources)):
        raise PageDataError('page columns must be immutable sequences')
    if not body.codes or len(body.codes) != len(body.readings) or len(body.codes) != len(body.sources):
        raise PageDataError('page columns must be nonempty and aligned')
    for code, reading, source in zip(body.codes, body.readings, body.sources, strict=True):
        if type(code) is not int or code < 0:
            raise PageDataError('invalid category code')
        if reading is not None and type(reading) is not int:
            raise PageDataError('invalid litre reading')
        if not isinstance(source, SourcePosition):
            raise PageDataError('invalid source position')
        try:
            require_name(source.partition, 'source partition')
            require_name(source.submission_id, 'source submission ID')
        except ValueError as exc:
            raise PageDataError('invalid source position') from exc
        if type(source.row_number) is not int or source.row_number < 1:
            raise PageDataError('invalid source row number')
