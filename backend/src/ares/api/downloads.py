"""HTTP filename encoding shared by all download routes."""
import re
import unicodedata
from urllib.parse import quote


def content_disposition(filename: str, *, inline: bool = False) -> str:
    name = filename.replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(ch for ch in name if ord(ch) >= 32 and ord(ch) != 127) or 'download'
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    fallback = re.sub(r'[^A-Za-z0-9 ._-]', '_', ascii_name).strip(' .') or 'download'
    kind = 'inline' if inline else 'attachment'
    if name == fallback and name.isascii():
        return f'{kind}; filename="{fallback}"'
    return f'{kind}; filename="{fallback}"; filename*=UTF-8\'\'{quote(name, safe="")}'
