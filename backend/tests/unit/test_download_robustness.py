from pathlib import Path
from urllib.parse import unquote

from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.api.downloads import content_disposition
from ares.application.research_stages.synthesis import _query_identifiers


def test_unicode_download_filename_is_ascii_header_with_utf8_name():
    header = content_disposition('अनुसंधान.pdf')
    header.encode('latin-1')
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == 'अनुसंधान.pdf'
    assert '\r' not in content_disposition('bad\r\nname.pdf')


def test_prose_slashes_are_not_github_identifiers():
    assert _query_identifiers('and/or TCP/IP client/server') == set()
    assert 'github:owner/repo' in _query_identifiers('https://github.com/Owner/Repo')


def test_blob_chunks_preserve_a_bounded_range(tmp_path: Path):
    blobs = FilesystemBlobStore(tmp_path)
    key = blobs.put_bytes('test', b'0123456789' * 10)
    chunks = list(blobs.iter_bytes(key, start=7, end_inclusive=32, chunk_size=8))
    assert b''.join(chunks) == (b'0123456789' * 10)[7:33]
    assert all(len(chunk) <= 8 for chunk in chunks)
