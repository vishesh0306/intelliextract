"""Real worker process entrypoint (replaces the `rq worker` CLI in
docker-compose) so we can configure structured logging before the worker
starts — RQ's own internal logs then come out as the same JSON shape as
ours, since both go through the same root logger handler.
"""

import structlog
from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = structlog.get_logger()


def main() -> None:
    configure_logging()
    settings = get_settings()

    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue("default", connection=redis_conn)
    worker = Worker([queue], connection=redis_conn)

    logger.info("worker_starting", queue="default")
    worker.work()


if __name__ == "__main__":
    main()
