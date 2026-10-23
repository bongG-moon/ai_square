"""Company Flask application, imported by index.py as ``application``.

The launcher owns server startup. This file only creates and configures ``app``;
it does not select a server implementation, listening address, or port.
"""
import os
import sys
from pathlib import Path

from flask import Flask

# Same effective NLS_LANG value as the supplied company base code.
os.environ['NLS_LANG'] = '.UTF8'

if __package__ in {None, ''}:
    # Also supports copying/renaming this folder without its parent project.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _square_bootstrap import load_package
    __package__ = load_package().__name__

from . import init_app

app = Flask(__name__)
url_path = ''

# Register the existing UI, APIs, MongoDB and SSO routes on this exact instance.
# runtime_config.py selects 'sso' or 'mock'; hcputil is loaded only for SSO.
# The session secret is retained from configuration/MongoDB across restarts.
# /login and /login/<path:sub_path> are installed once by backend/auth.py.
init_app(app)
