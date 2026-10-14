"""Container health probe that respects production TrustedHost validation."""
import argparse
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def build_probe_request(path: str) -> Request:
    if path not in {'/health/live', '/health/ready'}:
        raise ValueError('unsupported health path')
    public_host = urlsplit(os.getenv('PUBLIC_BASE_URL', '')).hostname or '127.0.0.1'
    return Request('http://127.0.0.1:8000' + path, headers={'Host': public_host})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', choices=['/health/live', '/health/ready'], default='/health/live')
    args = parser.parse_args()
    # The target is fixed loopback HTTP; the public origin only supplies the Host header.
    with urlopen(build_probe_request(args.path), timeout=2) as response:  # noqa: S310 -- fixed loopback target.
        response.read(1024)


if __name__ == '__main__':
    main()
