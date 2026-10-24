"""Portable source-ZIP launcher. Run with this package's isolated Python environment."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit('P&T AI SQUARE MCP requires Python 3.11 or newer.')

from pt_square_mcp.__main__ import main

if __name__ == '__main__':
    raise SystemExit(main())
