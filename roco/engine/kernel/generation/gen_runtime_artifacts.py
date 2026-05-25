"""Generate engine-owned runtime dispatch artifacts."""

from __future__ import annotations

from roco.engine.kernel.generation.handler_artifacts import write_handler_artifacts


def main() -> None:
    handlers = write_handler_artifacts()
    print(f"runtime/handler_order.py: {len(handlers)} engine op names")
    print("runtime/handler_table.py: engine op dispatch table")


if __name__ == "__main__":
    main()
