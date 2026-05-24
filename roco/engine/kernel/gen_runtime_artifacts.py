"""Generate engine-owned runtime dispatch artifacts."""

from __future__ import annotations

from roco.engine.kernel.handler_artifacts import write_handler_artifacts


def main() -> None:
    handlers = write_handler_artifacts()
    print(f"handler_indices.py: {len(handlers)} engine handler constants")
    print("handler_table.py: engine op dispatch table")


if __name__ == "__main__":
    main()

