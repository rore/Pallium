import pytest

from storage.relay_codec import RelayCodecError, decode_parts, encode_parts, parts_projection, prepare_parts


def test_parts_codec_is_canonical_and_bounded():
    encoded = encode_parts(["שלום ", "世界"])
    assert decode_parts(encoded) == ["שלום ", "世界"]
    with pytest.raises(RelayCodecError):
        decode_parts('["one", "two"]')
    with pytest.raises(RelayCodecError):
        encode_parts(["x"] * 9)


@pytest.mark.parametrize("parts", [[], [""], [" "], ["ok\x00"], ["\ud800"], ["x"] * 9])
def test_prepare_parts_rejects_invalid_values(parts):
    with pytest.raises(RelayCodecError):
        prepare_parts(parts)


def test_prepare_parts_redacts_cross_part_secret_and_preserves_ordered_count():
    stored = prepare_parts(["Authorization: Bearer sec", "ret-value"])
    assert "secret-value" not in stored
    assert decode_parts(stored) == ["[REDACTED]", "[REDACTED]"]
    assert "secret-value" not in parts_projection(stored)


def test_prepare_parts_applies_bounds_after_redaction():
    stored = prepare_parts(["safe", "text"])
    assert parts_projection(stored) == "safetext"
    with pytest.raises(RelayCodecError):
        prepare_parts(["x" * 1501])

def test_prepared_parts_preserve_legacy_multiline_text():
    parts = ["Plan:\n\tfirst\r\nsecond", "review"]
    assert decode_parts(prepare_parts(parts)) == parts


@pytest.mark.parametrize("payload", ['["\ud800"]', '["\\ud800"]'])
def test_decode_parts_rejects_surrogates_as_codec_errors(payload):
    with pytest.raises(RelayCodecError):
        decode_parts(payload)
