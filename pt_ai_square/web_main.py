"""HCP Flask entry (web_main:app) and direct execution (python web_main.py).

create_app() constructs the Flask app and registers the homepage and HCP SSO
routes. Set PTAI_AUTH_MODE='sso' or 'mock' in runtime_config.py; do not duplicate
the sample's '/' or '/login' routes here. Importing this module exports `app`
without starting a second server. Only direct execution starts Waitress.
"""
import sys
from pathlib import Path

if __package__ in {None, ''}:
    # VS Code's Run Python File and `python path/to/web_main.py` have no package.
    # Resolve from this file, not the terminal's current directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pt_ai_square import create_app
    from pt_ai_square.__main__ import main
else:
    from . import create_app
    from .__main__ import main

if __name__ == '__main__':
    main(['run', *sys.argv[1:]])
else:
    app = create_app()
