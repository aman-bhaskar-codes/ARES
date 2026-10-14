"""Bounded XML for small remote metadata feeds; no DTDs or entities are accepted."""
import re
from xml.etree import ElementTree as ET


def parse_xml(content: str) -> ET.Element:
    if len(content.encode('utf-8')) > 2_000_000:
        raise ValueError('XML metadata exceeds the size limit')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', content, re.IGNORECASE):
        raise ValueError('XML DTD/entity declarations are not permitted')
    return ET.fromstring(content)  # noqa: S314 -- size bounded; DTD/entity declarations rejected.
