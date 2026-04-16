from __future__ import annotations

import argparse
import time

from app.core.config import get_settings
from app.services.indexing_worker import get_indexing_worker_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartCloud-X knowledge indexing worker")
    parser.add_argument("--once", action="store_true", help="Process at most one batch and exit")
    parser.add_argument("--processor-id", default=None, help="Override the worker processor id")
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Maximum number of events to process per batch",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=None,
        help="Override the idle polling interval for loop mode",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    worker = get_indexing_worker_service()

    if args.once:
        worker.process_available(limit=args.max_events, processor_id=args.processor_id)
        worker.flush_traces()
        return 0

    poll_seconds = (
        args.poll_seconds
        if isinstance(args.poll_seconds, (int, float)) and args.poll_seconds >= 0
        else settings.index_worker_poll_seconds
    )
    while True:
        processed = worker.process_available(limit=args.max_events, processor_id=args.processor_id)
        worker.flush_traces()
        if processed <= 0:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
