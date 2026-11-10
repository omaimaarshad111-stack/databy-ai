import logging
from contextvars import ContextVar

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
        force=True,
    )
    request_filter = RequestContextFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(request_filter)
