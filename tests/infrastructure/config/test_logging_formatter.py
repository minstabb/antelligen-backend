"""ExtraFieldsFormatter — §17 S4-4 구조화 로그 필드 노출 검증."""
import logging

from app.infrastructure.config.logging_config import (
    ExtraFieldsFormatter,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
)


def _make_record(msg: str, **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_format_without_extras_matches_base_format():
    formatter = ExtraFieldsFormatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    record = _make_record("hello")
    out = formatter.format(record)
    assert "hello" in out
    assert "|" not in out  # 구분자 없음


def test_format_appends_extras_as_key_value():
    formatter = ExtraFieldsFormatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    record = _make_record(
        "batch done",
        llm_op="title_batch",
        batches=3,
        items=42,
    )
    out = formatter.format(record)
    # 기본 메시지 보존
    assert "batch done" in out
    # 모든 extra 노출
    assert "llm_op='title_batch'" in out
    assert "batches=3" in out
    assert "items=42" in out
    # 구분자 존재
    assert " | " in out


def test_format_handles_numeric_and_nested_extras():
    formatter = ExtraFieldsFormatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    record = _make_record(
        "macro rank",
        llm_op="macro_importance",
        elapsed_ms=1234.5,
        failures={"400": 2},
    )
    out = formatter.format(record)
    assert "elapsed_ms=1234.5" in out
    assert "failures={'400': 2}" in out


def test_format_excludes_standard_record_attrs():
    """asctime/levelname 등이 extras 로 오인되어 중복 노출되지 않아야 함."""
    formatter = ExtraFieldsFormatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    record = _make_record("noop")
    out = formatter.format(record)
    # levelname은 base format으로 이미 노출됨 → suffix 없음
    assert " | " not in out
