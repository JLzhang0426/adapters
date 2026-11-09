"""
Main entry point for the template adapter. Do not modify any of the existing flags.
You can add any additional flags you need.

Constructs the Adapter class defined in adapter.py and calls run() to generate tasks
in the Harbor format at the configured output directory.
"""

import argparse
from pathlib import Path

from .adapter import LongBenchV2Adapter

# Default output dir: <repo>/datasets/<adapter_id>
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[4] / "datasets" / "longbench-v2"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write generated tasks",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Generate only the first N tasks",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing tasks",
    )
    parser.add_argument(
        "--task-ids",
        nargs="+",
        default=None,
        help="Only generate these task IDs",
    )
    parser.add_argument(
        "--split",
        choices=["full", "parity"],
        default="full",
        help="full = all 503 questions; parity = stratified subset for parity runs",
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        default=None,
        help="Path to LongBench v2 data.json (default: $LONGBENCH_V2_DATA or .cache/longbench-v2/data.json, downloaded if missing)",
    )
    parser.add_argument(
        "--skip-checksum",
        action="store_true",
        help="Do not verify data.json against the pinned sha256 (tasks will not be comparable to the registered benchmark)",
    )
    args = parser.parse_args()

    adapter = LongBenchV2Adapter(
        args.output_dir,
        overwrite=args.overwrite,
        limit=args.limit,
        task_ids=args.task_ids,
        split=args.split,
        data_path=args.data_path,
        skip_checksum=args.skip_checksum,
    )

    adapter.run()


if __name__ == "__main__":
    main()
