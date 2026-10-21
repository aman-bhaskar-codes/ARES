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
    assert '\n' not in content_disposition('bad\r\nname.pdf')


def test_content_disposition_sanitizes_quotes_and_traversal():
    header_quotes = content_disposition('attack"injection";evil.pdf')
    header_quotes.encode('latin-1')
    assert '"attack_injection_evil.pdf"' in header_quotes or '"attack_injection__evil.pdf"' in header_quotes
    assert '\r' not in header_quotes and '\n' not in header_quotes

    header_crlf = content_disposition('file\r\nSet-Cookie: evil=1\r\n.pdf')
    header_crlf.encode('latin-1')
    assert '\r' not in header_crlf and '\n' not in header_crlf

    header_traversal = content_disposition('../../secret/report.pdf')
    assert '..' not in header_traversal.split('filename="', 1)[1].split('"', 1)[0]
    assert '/' not in header_traversal.split('filename="', 1)[1].split('"', 1)[0]

    header_emoji = content_disposition('research_report_🚀.pdf')
    header_emoji.encode('latin-1')
    assert unquote(header_emoji.split("filename*=UTF-8''", 1)[1]) == 'research_report_🚀.pdf'


def test_prose_slashes_are_not_github_identifiers():
    assert _query_identifiers('and/or TCP/IP client/server') == set()
    assert 'github:owner/repo' in _query_identifiers('https://github.com/Owner/Repo')


def test_blob_chunks_preserve_a_bounded_range(tmp_path: Path):
    blobs = FilesystemBlobStore(tmp_path)
    key = blobs.put_bytes('test', b'0123456789' * 10)
    chunks = list(blobs.iter_bytes(key, start=7, end_inclusive=32, chunk_size=8))
    assert b''.join(chunks) == (b'0123456789' * 10)[7:33]
    assert all(len(chunk) <= 8 for chunk in chunks)
