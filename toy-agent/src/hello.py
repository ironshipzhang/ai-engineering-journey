"""Verify the project's Python runtime; no model API is called."""

import platform
import sys


def main() -> None:
    print("Toy Agent: Python environment is ready.")
    print(f"Python: {platform.python_version()}")
    print(f"Architecture: {platform.machine()}")
    print(f"Virtual environment: {sys.prefix != sys.base_prefix}")


if __name__ == "__main__":
    main()
