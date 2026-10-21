"""Read-time normalization preserves import values and bounded streaming."""

import io
from datetime import UTC, date, datetime
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dq_scoring.adapters.source.tabular_normalization import (
    ImportInspectionException,
    inspect_schema,
    iter_normalized_batches,
)


def normalized(data, fmt, **kwargs):
    raw = io.BytesIO(data)
    spec = inspect_schema(raw, file_format=fmt, column_names_mapping=None, **kwargs)
    raw.seek(0)
    scanned = []
    batches = list(iter_normalized_batches(raw, spec, scan_row=scanned.append))
    assert not raw.closed
    return spec, pa.Table.from_batches(batches).to_pylist(), scanned


def test_csv_preserves_bom_multiline_whitespace_and_leading_zero():
    spec, rows, scanned = normalized(b'\xef\xbb\xbf id ; note ;empty\n001;"a\nb";\n002;  ;x\n', 'CSV', delimiter=';')
    assert [c['name'] for c in spec.columns] == ['id', 'note', 'empty']
    assert rows == scanned == [
        {'id': '001', 'note': 'a\nb', 'empty': None},
        {'id': '002', 'note': '  ', 'empty': 'x'},
    ]


def test_json_union_precision_and_container_scalar_encoding():
    spec, rows, scanned = normalized(
        b'{"a":9007199254740993.123,"mixed":{"n":1},"flag":true}\n\n'
        b'{"mixed":"text","later":[false]}\n', 'JSONL')
    assert spec.version == 2
    assert rows == [
        {'a': '9007199254740993.123', 'mixed': '{"n":1}', 'flag': 'true', 'later': None},
        {'a': None, 'mixed': '"text"', 'flag': None, 'later': '[false]'},
    ]
    assert scanned == [
        {'a': Decimal('9007199254740993.123'), 'mixed': {'n': 1}, 'flag': True, 'later': None},
        {'a': None, 'mixed': 'text', 'flag': None, 'later': [False]},
    ]


def test_parquet_arrow_scalar_and_nested_values():
    table = pa.table({
        'amount': pa.array([Decimal('123.40')], type=pa.decimal128(12, 2)),
        'day': pa.array([date(2025, 1, 2)], type=pa.date32()),
        'at': pa.array([datetime(2025, 1, 2, 3, 4, tzinfo=UTC)], type=pa.timestamp('us', tz='UTC')),
        'obj': pa.array([{'n': 2}], type=pa.struct([('n', pa.int64())])),
        'map': pa.array([[('x', Decimal('1.20'))]], type=pa.map_(pa.string(), pa.decimal128(5, 2))),
        'list': pa.array([[True, False]], type=pa.list_(pa.bool_())),
    })
    buf = io.BytesIO()
    pq.write_table(table, buf)
    spec, rows, scanned = normalized(buf.getvalue(), 'PARQUET')
    assert spec.version == 2
    assert rows == [{'amount': '123.40', 'day': '2025-01-02', 'at': '2025-01-02 03:04:00.000000Z',
                     'obj': '{"n":2}', 'map': '{"x":1.20}', 'list': '[true,false]'}]
    assert scanned[0]['obj'] == {'n': 2}
    assert scanned[0]['amount'] == '123.40'


@pytest.mark.parametrize(('data', 'fmt', 'code'), [
    (b'a,a\n1,2\n', 'CSV', 'DUPLICATE_COLUMN_NAME'),
    (b'a\n"unfinished\n', 'CSV', 'MALFORMED_CSV'),
    (b'a\n\xff\n', 'CSV', 'MALFORMED_CSV'),
    (b'a\n', 'CSV', 'EMPTY_DATASET'),
    (b'{"x":1,"x":2}\n', 'JSONL', 'MALFORMED_JSONL'),
    (b'{"x":' + b'[' * 33 + b'1' + b']' * 33 + b'}\n', 'JSONL', 'NESTING_TOO_DEEP'),
])
def test_invalid_input_keeps_error_codes(data, fmt, code):
    with pytest.raises(ImportInspectionException) as exc:
        normalized(data, fmt)
    assert exc.value.error_code == code


def test_batches_do_not_exceed_row_or_text_bounds():
    data = b'v\n' + (b'x' * 4096 + b'\n') * 9000
    raw = io.BytesIO(data)
    spec = inspect_schema(raw, file_format='CSV', column_names_mapping=None)
    raw.seek(0)
    batches = list(iter_normalized_batches(raw, spec))
    assert sum(b.num_rows for b in batches) == 9000
    assert all(b.num_rows <= 8192 for b in batches)
    assert all(sum(len(v['v'].encode()) for v in b.to_pylist()) <= 16 * 1024 * 1024 for b in batches)


@pytest.mark.parametrize('record', [
    b'x' * 40 + b',' + b'y' * 40 + b',' + b'z' * 40 + b'\n',
    b'"' + (b'x' * 30 + b'\n') * 4 + b'",y,z\n',
])
@pytest.mark.parametrize('header', [False, True])
def test_csv_logical_record_rejected_before_full_consumption(monkeypatch, record, header):
    import dq_scoring.adapters.source.tabular_normalization as module
    monkeypatch.setattr(module, 'MAX_RECORD_BYTES', 64)
    class TrackingBytes(io.BytesIO):
        consumed = 0
        def read1(self, size=-1):
            data = super().read1(min(size, 8) if size >= 0 else 8)
            self.consumed += len(data)
            return data
    raw = TrackingBytes(record if header else b'a,b,c\n' + record)
    with pytest.raises(ImportInspectionException) as error:
        if header:
            inspect_schema(raw, file_format='CSV', column_names_mapping=None)
        else:
            spec = inspect_schema(io.BytesIO(b'a,b,c\n'), file_format='CSV', column_names_mapping=None)
            list(iter_normalized_batches(raw, spec))
    assert error.value.error_code == 'RECORD_TOO_LARGE'
    assert raw.consumed < len(raw.getvalue())


@pytest.mark.parametrize('ending', ['\n', '\r\n', '\r'])
def test_csv_chunk_boundary_preserves_quoted_newlines(ending):
    value = 'x' * 65535 + ending + 'y'
    data = ('a,b' + ending + '"' + value + '",001' + ending).encode()
    _, rows, _ = normalized(data, 'CSV')
    assert rows == [{'a': value, 'b': '001'}]
