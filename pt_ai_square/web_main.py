"""HCP Flask entry (web_main:app) and direct execution (python web_main.py).

create_app() constructs the Flask app and registers the homepage and HCP SSO
routes. Set PTAI_AUTH_MODE='sso' or 'mock' in runtime_config.py; do not duplicate
the sample's '/' or '/login' routes here. Importing this module exports `app`
without starting a second server. Direct execution starts the local server.
"""
import sys
from pathlib import Path

if __package__ in {None, ''}:
    # Resolve only this folder; it may be renamed or deployed as the app root.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _square_bootstrap import load_package
    __package__ = load_package().__name__

from . import create_app
from .__main__ import main

if __name__ == '__main__':
    main(['run', *sys.argv[1:]])
else:
    app = create_app()
