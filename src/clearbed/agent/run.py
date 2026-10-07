"""Command-line entry for one copilot run.

The process stops when a person must approve. It never marks a referral sent.
"""

from __future__ import annotations

import argparse
import json

from clearbed.agent.graph import start_run
from clearbed.config import get_settings
from clearbed.logging import configure_logging


def main() -> None:
    """Start a run for ``--stay-id`` and print the public view as JSON."""
    parser = argparse.ArgumentParser(description="Run the ClearBed discharge copilot for one stay.")
    parser.add_argument("--stay-id", required=True)
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings)
    view = start_run(args.stay_id, settings)
    print(json.dumps(view, indent=2, default=str))
    if view.get("status") == "awaiting_approval":
        print("Waiting for a human decision. Nothing was sent.")


if __name__ == "__main__":
    main()
