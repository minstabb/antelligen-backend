import logging
import os
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "logs")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 표준 LogRecord 속성 — `extra=` 로 주입된 필드만 골라내기 위한 제외 목록.
# 항목이 바뀔 일이 거의 없어 하드코딩. (CPython logging 모듈 참조)
_STANDARD_LOGRECORD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
})


class ExtraFieldsFormatter(logging.Formatter):
    """`extra=` 로 주입된 필드를 메시지 뒤에 `key=value` 로 붙이는 Formatter.

    §17 S4-4: 기존 Formatter 문자열에 `%(llm_op)s` 가 없어 구조화 로그가
    파일에 0건 관측되던 문제 해소. 호출 시마다 달라지는 extra 키(`llm_op`,
    `elapsed_ms`, `batches`, `latency_p95_s` 등)를 정적 포맷에 하드코딩하면
    KeyError 가 나므로, record의 __dict__ 에서 표준 속성을 제외한 나머지를
    동적으로 직렬화.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in _STANDARD_LOGRECORD_ATTRS and not k.startswith("_")
        }
        if not extras:
            return base
        suffix = " ".join(f"{k}={v!r}" for k, v in extras.items())
        return f"{base} | {suffix}"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with console + daily rotating file handlers.

    Log files are written to <project_root>/logs/ with daily rotation
    and 30-day retention. Safe to call multiple times — skips if already configured.
    """
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = ExtraFieldsFormatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Console handler (stdout)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # File handler — rotates daily at midnight, keeps 30 days
    # Naming: logs/app.log (current), logs/20260330-app.log (rotated)
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, "app.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y%m%d"
    file_handler.namer = lambda name: os.path.join(
        os.path.dirname(name),
        os.path.basename(name).replace("app.log.", "") + "-app.log",
    )

    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # httpx의 기본 INFO 로그는 URL을 query string 포함 그대로 출력하기 때문에
    # 외부 API 키(crtfc_key, key 등)가 평문으로 노출된다. WARNING 이상만 남긴다.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
