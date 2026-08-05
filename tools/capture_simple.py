#!/usr/bin/env python3
# ruff: noqa: T201
"""Compatibility entry point for the maintained TYDOM capture tool.

Historically this repository carried two independent capture implementations.
Keeping one implementation prevents their request lists, parser and safety
behaviour from drifting apart again.
"""

from __future__ import annotations

import asyncio
import sys

try:
    from .capture_tydom_data import main
except ImportError:  # Direct execution: python tools/capture_simple.py
    from capture_tydom_data import main


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Interrompu")
        sys.exit(0)
