from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, cast
from zipfile import BadZipFile, ZipFile

import fastexcel
import polars as pl

type ExcelSource = str | Path | bytes | BinaryIO

MAX_WORKBOOK_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 1_000


class MissingExpectedSheetError(Exception):
    pass


class DuplicateColumnError(Exception):
    def __init__(self, column: str) -> None:
        self.column = column
        super().__init__(column)


class WorkbookTooLargeError(Exception):
    pass


class WorkbookTooComplexError(Exception):
    pass


class UnreadableWorkbookError(Exception):
    pass


def _prepare_source(source: ExcelSource) -> str | bytes:
    if isinstance(source, Path):
        if source.stat().st_size > MAX_WORKBOOK_BYTES:
            raise WorkbookTooLargeError
        return str(source)
    if isinstance(source, str):
        path = Path(source)
        if path.stat().st_size > MAX_WORKBOOK_BYTES:
            raise WorkbookTooLargeError
        return source
    if isinstance(source, bytes):
        if len(source) > MAX_WORKBOOK_BYTES:
            raise WorkbookTooLargeError
        return source
    if isinstance(source, BytesIO):
        if source.getbuffer().nbytes > MAX_WORKBOOK_BYTES:
            raise WorkbookTooLargeError
        return source.getvalue()

    position = source.tell()
    try:
        source.seek(0, 2)
        if source.tell() > MAX_WORKBOOK_BYTES:
            raise WorkbookTooLargeError
        source.seek(0)
        return source.read()
    finally:
        source.seek(position)


def _validate_archive(excel_source: str | bytes) -> None:
    archive_source = BytesIO(excel_source) if isinstance(excel_source, bytes) else excel_source
    with ZipFile(archive_source) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise WorkbookTooComplexError
        if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
            raise WorkbookTooLargeError


def read_workbook(source: ExcelSource, sheet_name: str) -> pl.DataFrame:
    try:
        excel_source = _prepare_source(source)
        _validate_archive(excel_source)
        workbook = fastexcel.read_excel(excel_source)
        if sheet_name not in workbook.sheet_names:
            raise MissingExpectedSheetError(sheet_name)

        header_sheet = workbook.load_sheet_by_name(sheet_name, header_row=None, n_rows=1)
        header_data = cast(pl.DataFrame, pl.from_arrow(header_sheet.to_arrow()))
        headers = list(header_data.row(0)) if header_data.height else []
        duplicate = next(
            (
                header
                for header, count in Counter(headers).items()
                if header is not None and count > 1
            ),
            None,
        )
        if duplicate is not None:
            raise DuplicateColumnError(str(duplicate))

        sheet = workbook.load_sheet_by_name(sheet_name)
        return cast(pl.DataFrame, pl.from_arrow(sheet.to_arrow()))
    except (
        DuplicateColumnError,
        MissingExpectedSheetError,
        WorkbookTooComplexError,
        WorkbookTooLargeError,
    ):
        raise
    except (BadZipFile, OSError, ValueError, fastexcel.FastExcelError) as error:
        raise UnreadableWorkbookError from error
