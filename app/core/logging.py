import logging
import sys

import structlog


def configure_logging() -> None:
    """Wires structlog into stdlib logging so both our own structured log
    calls and third-party logs (uvicorn access logs, SQLAlchemy, etc.) come
    out as the same JSON shape on stdout. contextvars.merge_contextvars is
    what makes bind_contextvars(job_id=...)/request_id=... automatically
    appear on every log line emitted while that context is active, without
    threading a logger instance through every function call.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # foreign_pre_chain applies the same shared processors to log
        # records that came from plain stdlib logging (uvicorn, RQ,
        # SQLAlchemy) rather than structlog.get_logger() — without this
        # they'd render as JSON but without level/timestamp/context fields.
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # Formats an exc_info=<exception> kwarg into a proper traceback
            # string before rendering — without this, exceptions logged via
            # logger.error(..., exc_info=exc) don't actually show up.
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)
