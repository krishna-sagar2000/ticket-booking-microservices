"""JSON logs to the console, with the correlation id on every line."""
import logging
import sys
from contextvars import ContextVar
from pythonjsonlogger import jsonlogger

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


class _CorrelationFilter(logging.Filter):
    def filter(self, record):
        record.correlationId = correlation_id_var.get()
        return True


def setup_logging(service_name: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(correlationId)s %(message)s")
    )
    handler.addFilter(_CorrelationFilter())
    logger = logging.getLogger(service_name)
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
