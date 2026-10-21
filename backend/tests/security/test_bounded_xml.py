import pytest
from ares.adapters.safe_xml import parse_xml


def test_untrusted_xml_rejects_entity_definitions():
    with pytest.raises(ValueError):
        parse_xml('<!DOCTYPE x [<!ENTITY a "expanded">]><x>&a;</x>')
    assert parse_xml('<x>plain</x>').text == 'plain'


def test_untrusted_xml_has_a_size_bound():
    with pytest.raises(ValueError):
        parse_xml('<x>' + 'a' * 2_000_001 + '</x>')
