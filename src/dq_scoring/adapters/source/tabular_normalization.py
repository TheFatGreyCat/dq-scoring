"""Bounded, deterministic tabular normalization shared by import and readers."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from dq_scoring.common.structured_values import (
    StructuredParsingError,
    canonical_compact_json,
    classify_value_kind,
    parse_structured_json,
)

MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_BATCH_BYTES = 16 * 1024 * 1024
MAX_BATCH_ROWS = 8192


class ImportInspectionException(Exception):
    """An uploaded dataset violates a supported format or structural bound."""

    def __init__(self, error_code: str, detail: str, invalid_params: list[dict[str, Any]] | None = None) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.invalid_params = invalid_params


@dataclass(frozen=True)
class NormalizationSpec:
    version: int
    format: Literal['CSV', 'JSONL', 'PARQUET']
    columns: tuple[dict[str, Any], ...]
    delimiter: str = ','
    encoding: Literal['utf-8-sig'] = 'utf-8-sig'


@contextmanager
def _text(raw: BinaryIO):
    wrapper = io.TextIOWrapper(raw, encoding='utf-8-sig', newline='')
    try:
        yield wrapper
    finally:
        wrapper.detach()



def _csv_rows(raw: BinaryIO, delimiter: str) -> Iterator[list[str]]:
    csv.field_size_limit(MAX_RECORD_BYTES)
    with _text(raw) as text:
        consumed = 0

        def lines():
            nonlocal consumed
            pending = ''
            while True:
                pieces = []
                while True:
                    part = pending + text.readline(min(64 * 1024, MAX_RECORD_BYTES - consumed + 1))
                    pending = ''
                    if not part:
                        if pieces:
                            yield ''.join(pieces)
                        return
                    if part.endswith('\r'):
                        following = text.read(1)
                        if following == '\n':
                            part += following
                        else:
                            pending = following
                    consumed += len(part.encode('utf-8'))
                    if consumed > MAX_RECORD_BYTES:
                        raise ImportInspectionException('RECORD_TOO_LARGE', 'CSV record exceeds 8 MiB')
                    pieces.append(part)
                    if part.endswith(('\n', '\r')):
                        break
                yield ''.join(pieces)

        reader = csv.reader(lines(), delimiter=delimiter, strict=True)
        while True:
            consumed = 0
            row = next(reader, None)
            if row is None:
                return
            yield row

def _columns(names: list[str], mapping: list[str] | None, *, csv_header: bool = False) -> list[dict[str, Any]]:
    if not names:
        raise ImportInspectionException('EMPTY_DATASET', 'Dataset contains no columns')
    if len(names) > 1000:
        raise ImportInspectionException('TOO_MANY_COLUMNS', 'Schema exceeds 1000 columns')
    if csv_header and not mapping:
        empty = [i for i, name in enumerate(names) if not name]
        if empty:
            raise ImportInspectionException('EMPTY_COLUMN_NAME', 'Empty column names',
                [{'name': f'col_{i}', 'code': 'EMPTY_COLUMN_NAME', 'index': i} for i in empty])
        positions: dict[str, list[int]] = {}
        for i, name in enumerate(names):
            positions.setdefault(name, []).append(i)
        duplicates = {k: v for k, v in positions.items() if len(v) > 1}
        if duplicates:
            raise ImportInspectionException('DUPLICATE_COLUMN_NAME', 'Duplicate column names',
                [{'name': k, 'code': 'DUPLICATE_COLUMN_NAME', 'indices': v} for k, v in duplicates.items()])
    final = mapping if mapping else names
    if len(final) != len(names) or len(set(final)) != len(final) or any(not n for n in final):
        raise ImportInspectionException('INVALID_COLUMN_MAPPING', 'Mapped columns must be nonempty and one-to-one')
    return [{'index': i, 'original_name': names[i], 'name': n, 'type': 'STRING', 'nullable': True}
            for i, n in enumerate(final)]


def _json_rows(raw: BinaryIO) -> Iterator[dict[str, Any]]:
    try:
        with _text(raw) as text:
            while line := text.readline(MAX_RECORD_BYTES + 2):
                if len(line.encode('utf-8')) > MAX_RECORD_BYTES:
                    raise ImportInspectionException('RECORD_TOO_LARGE', 'JSONL record exceeds 8 MiB')
                if not line.strip():
                    continue
                try:
                    obj = parse_structured_json(line.strip(), max_depth=32)
                except StructuredParsingError as exc:
                    code = 'NESTING_TOO_DEEP' if exc.error_code == 'NESTING_TOO_DEEP' else 'MALFORMED_JSONL'
                    raise ImportInspectionException(code, 'Invalid JSONL record') from exc
                if not isinstance(obj, dict):
                    raise ImportInspectionException('NESTED_DATA_UNSUPPORTED', 'JSONL root must be an object')
                yield obj
    except UnicodeDecodeError as exc:
        raise ImportInspectionException('MALFORMED_JSONL', 'Invalid UTF-8') from exc


def _parquet(raw: BinaryIO) -> pq.ParquetFile:
    try:
        parquet = pq.ParquetFile(raw)
        for i in range(parquet.num_row_groups):
            if parquet.metadata.row_group(i).total_byte_size > 256 * 1024 * 1024:
                raise ImportInspectionException('PARQUET_ROW_GROUP_TOO_LARGE', 'Row group exceeds 256 MiB')
        return parquet
    except ImportInspectionException:
        raise
    except (pa.ArrowException, ValueError) as exc:
        raise ImportInspectionException('MALFORMED_PARQUET', 'Invalid Parquet file') from exc


def inspect_schema(raw: BinaryIO, *, file_format: str, column_names_mapping: list[str] | None,
                   delimiter: str = ',', warnings: list[str] | None = None) -> NormalizationSpec:
    fmt = file_format.upper()
    version = 1
    if fmt == 'CSV':
        if delimiter not in (',', ';', '\t', '|'):
            raise ImportInspectionException('MALFORMED_CSV', 'Unsupported delimiter')
        records = _csv_rows(raw, delimiter)
        try:
            header = next(records, None)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ImportInspectionException('MALFORMED_CSV', 'Invalid CSV header') from exc
        finally:
            records.close()
        if not header or all(not h.strip() for h in header):
            raise ImportInspectionException('EMPTY_DATASET', 'CSV has no valid header')
        columns = _columns([h.strip() for h in header], column_names_mapping, csv_header=True)
    elif fmt == 'JSONL':
        kinds: dict[str, set[str]] = {}
        for obj in _json_rows(raw):
            for name, val in obj.items():
                kinds.setdefault(name, set()).add(classify_value_kind(val))
                if len(kinds) > 1000:
                    raise ImportInspectionException('TOO_MANY_COLUMNS', 'JSONL union exceeds 1000 columns')
        columns = _columns(list(kinds), column_names_mapping)
        if warnings is not None and any(len(values) > 1 for values in kinds.values()):
            warnings.append('MIXED_SCALAR_TYPES')
        for col in columns:
            logical = kinds[col['original_name']]
            if logical & {'OBJECT', 'ARRAY'}:
                col.update(structural_encoding='JSON', logical_types=sorted(logical))
                version = 2
    elif fmt == 'PARQUET':
        parquet = _parquet(raw)
        schema = parquet.schema_arrow
        columns = _columns(schema.names, column_names_mapping)
        for col, field in zip(columns, schema, strict=True):
            typ = field.type
            if pa.types.is_binary(typ) or pa.types.is_large_binary(typ) or pa.types.is_union(typ):
                raise ImportInspectionException('UNSUPPORTED_FORMAT', 'Binary or union column unsupported')
            col['type'] = str(typ)
            if pa.types.is_nested(typ):
                is_list = pa.types.is_list(typ) or pa.types.is_large_list(typ) or pa.types.is_fixed_size_list(typ)
                col.update(structural_encoding='JSON', logical_types=['ARRAY' if is_list else 'OBJECT'])
                version = 2
    else:
        raise ImportInspectionException('UNSUPPORTED_FORMAT', 'Unsupported format')
    if len(json.dumps(columns).encode('utf-8')) > 500 * 1024:
        raise ImportInspectionException('SCHEMA_TOO_LARGE', 'Schema exceeds 500 KiB')
    return NormalizationSpec(version=version, format=fmt, columns=tuple(columns), delimiter=delimiter)


def _arrow_json_value(value: Any, arrow_type: pa.DataType, depth: int = 1) -> Any:
    if depth > 32:
        raise ImportInspectionException('NESTING_TOO_DEEP', 'Parquet nesting exceeds 32 levels')
    if value is None:
        return None
    if pa.types.is_map(arrow_type):
        result = {}
        for key, item in value:
            if not isinstance(key, str):
                raise ImportInspectionException('UNSUPPORTED_FORMAT', 'Map keys must be strings')
            if key in result:
                raise ImportInspectionException('DUPLICATE_KEY', 'Duplicate map key')
            result[key] = _arrow_json_value(item, arrow_type.item_type, depth + 1)
        return result
    if pa.types.is_struct(arrow_type):
        return {f.name: _arrow_json_value(value.get(f.name), f.type, depth + 1) for f in arrow_type}
    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type) or pa.types.is_fixed_size_list(arrow_type):
        return [_arrow_json_value(v, arrow_type.value_type, depth + 1) for v in value]
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type) or pa.types.is_union(arrow_type):
        raise ImportInspectionException('UNSUPPORTED_FORMAT', 'Binary or union nested value unsupported')
    return value


def _normalized_rows(raw: BinaryIO, spec: NormalizationSpec, row_groups: tuple[int, ...] | None):
    names = [c['name'] for c in spec.columns]
    if spec.format == 'CSV':
        records = _csv_rows(raw, spec.delimiter)
        try:
            next(records, None)
            for row in records:
                if len(row) != len(names):
                    raise ImportInspectionException('MALFORMED_CSV', 'CSV row width differs from header')
                vals = [v if v != '' else None for v in row]
                yield vals, dict(zip(names, vals, strict=True))
        except (csv.Error, UnicodeDecodeError) as exc:
            raise ImportInspectionException('MALFORMED_CSV', 'CSV syntax or UTF-8 is invalid') from exc
        finally:
            records.close()
    elif spec.format == 'JSONL':
        for obj in _json_rows(raw):
            vals = []
            scan = {}
            for col in spec.columns:
                val = obj.get(col['original_name'])
                scan[col['name']] = val
                if val is None:
                    vals.append(None)
                elif col.get('structural_encoding') == 'JSON':
                    vals.append(canonical_compact_json(val))
                elif isinstance(val, bool):
                    vals.append('true' if val else 'false')
                else:
                    vals.append(str(val))
            yield vals, scan
    else:
        parquet = _parquet(raw)
        for batch in parquet.iter_batches(batch_size=MAX_BATCH_ROWS, row_groups=list(row_groups) if row_groups is not None else None):
            converted = []
            for i, col in enumerate(spec.columns):
                array = batch.column(i)
                if col.get('structural_encoding') == 'JSON':
                    values = []
                    for value in array.to_pylist():
                        if value is None:
                            values.append(None)
                        else:
                            encoded = canonical_compact_json(_arrow_json_value(value, array.type))
                            try:
                                parse_structured_json(encoded)
                            except StructuredParsingError as exc:
                                raise ImportInspectionException(exc.error_code, 'Invalid nested Parquet value') from exc
                            values.append(encoded)
                    converted.append(pa.array(values, type=pa.string()))
                else:
                    converted.append(array.cast(pa.string()))
            for r in range(batch.num_rows):
                vals = [a[r].as_py() for a in converted]
                scan = {col['name']: parse_structured_json(v) if v is not None and col.get('structural_encoding') == 'JSON' else v
                        for col, v in zip(spec.columns, vals, strict=True)}
                yield vals, scan


def iter_normalized_batches(raw: BinaryIO, spec: NormalizationSpec, *, row_groups: tuple[int, ...] | None = None,
                            scan_row: Callable[[dict[str, Any]], None] | None = None) -> Iterator[pa.RecordBatch]:
    names = [c['name'] for c in spec.columns]
    schema = pa.schema([pa.field(n, pa.string()) for n in names], metadata={'normalization_version': str(spec.version)})
    rows = []
    size = 0
    count = 0

    def batch():
        return pa.RecordBatch.from_arrays([pa.array([row[i] for row in rows], type=pa.string())
                                          for i in range(len(names))], schema=schema)

    for values, scan in _normalized_rows(raw, spec, row_groups):
        record_size = sum(len(v.encode('utf-8')) for v in values if v is not None)
        if record_size > MAX_RECORD_BYTES:
            raise ImportInspectionException('RECORD_TOO_LARGE', 'Normalized record exceeds 8 MiB')
        if rows and (len(rows) >= MAX_BATCH_ROWS or size + record_size > MAX_BATCH_BYTES):
            yield batch()
            rows.clear()
            size = 0
        if scan_row is not None:
            scan_row(scan)
        rows.append(values)
        size += record_size
        count += 1
    if rows:
        yield batch()
    if count == 0:
        raise ImportInspectionException('EMPTY_DATASET', 'Dataset contains 0 rows')
