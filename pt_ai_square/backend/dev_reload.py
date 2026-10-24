"""Keep uploaded archives out of the optional development code reloader."""
from pathlib import Path


def upload_reload_excludes(data_dir):
    """Exclude only the two flat upload stores, even if DATA_DIR is the app root.

    Werkzeug's watchdog backend watches *.zip as well as Python sources. A
    package inspection or publication writes/deletes a ZIP in these stores and
    can otherwise restart a debug server in the middle of its HTTP response.
    Keep normal source reloads and the company's startup/host/port unchanged.
    """
    root = Path(data_dir).resolve()
    patterns = []
    for name in ('artifacts', 'request_attachments'):
        directory = (root / name).resolve()
        # Configured paths can contain glob characters (e.g. "[team]").
        literal = ''.join({'[': '[[]', ']': '[]]', '?': '[?]', '*': '[*]'}.get(c, c)
                          for c in directory.as_posix())
        patterns.extend((literal, literal + '/*'))
    return patterns
