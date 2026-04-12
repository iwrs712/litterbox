from __future__ import annotations

import argparse
import logging

from orchestrator.container import build_container


def main() -> None:
    parser = argparse.ArgumentParser(description="Run orchestrator worker")
    parser.add_argument("worker", choices=["ttl"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    container = build_container()
    if args.worker == "ttl":
        container.ttl_worker.run_forever()


if __name__ == "__main__":
    main()
