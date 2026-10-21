"""Shared test factories; each call owns its mutable state."""

import io
import zipfile


def archive(value=b"v1", name="sdk/readme", compression=zipfile.ZIP_STORED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as z:
        z.writestr(name, value)
    stream.seek(0)
    return stream
