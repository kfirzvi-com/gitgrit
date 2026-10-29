"""MkDocs hook: version our stylesheet URLs by content.

The site is served with `Cache-Control: max-age=3600` on every file, and our
stylesheets keep fixed names (stylesheets/custom.css). After a deploy a
returning visitor got the new HTML with the cached old CSS, and the page
broke until the cache expired. Appending `?v=<content hash>` gives a
changed file a new URL, while unchanged files keep theirs and stay cached.
"""

import hashlib
from pathlib import Path


def on_config(config):
    docs_dir = Path(config["docs_dir"])
    config["extra_css"] = [_versioned(docs_dir, path) for path in config["extra_css"]]
    return config


def _versioned(docs_dir: Path, path: str) -> str:
    source = docs_dir / path
    if "://" in path or "?" in path or not source.is_file():
        return path
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:10]
    return f"{path}?v={digest}"
