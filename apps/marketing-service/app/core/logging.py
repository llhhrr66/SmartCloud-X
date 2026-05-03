import logging

logger = logging.getLogger("marketing-service")


class _RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, 'trace_id'):
            record.trace_id = '-'
        if not hasattr(record, 'request_id'):
            record.request_id = '-'
        return True


class _SafeExtraFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, 'trace_id'):
            record.trace_id = '-'
        if not hasattr(record, 'request_id'):
            record.request_id = '-'
        return super().format(record)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s trace_id=%(trace_id)s request_id=%(request_id)s %(message)s",
        force=True,
    )

    root_logger = logging.getLogger()
    context_filter = _RequestContextFilter()
    root_logger.addFilter(context_filter)
    for handler in root_logger.handlers:
        handler.addFilter(context_filter)
        if handler.formatter is not None:
            handler.setFormatter(_SafeExtraFormatter(handler.formatter._fmt, handler.formatter.datefmt))
