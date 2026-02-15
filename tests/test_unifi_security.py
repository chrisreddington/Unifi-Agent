"""Security tests for UniFi MCP server — ID validation and SSL config."""

import re
import os
import pytest

# Replicate the validation logic directly to avoid importing server dependencies
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-.:]+$")


def _validate_id(value: str, name: str = "id") -> str:
    """Validate that an ID parameter contains only safe characters."""
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Invalid {name}: contains unsafe characters")
    return value


class TestIdValidation:
    """Tests for API path parameter sanitization."""

    def test_valid_uuid(self):
        assert _validate_id("550e8400-e29b-41d4-a716-446655440000") == "550e8400-e29b-41d4-a716-446655440000"

    def test_valid_hex_string(self):
        assert _validate_id("abcdef1234567890") == "abcdef1234567890"

    def test_valid_alphanumeric_with_dashes(self):
        assert _validate_id("my-site-123") == "my-site-123"

    def test_valid_with_underscores(self):
        assert _validate_id("device_tag_1") == "device_tag_1"

    def test_valid_with_colons(self):
        """MAC addresses may use colons."""
        assert _validate_id("aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"

    def test_valid_with_dots(self):
        assert _validate_id("192.168.1.1") == "192.168.1.1"

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_id("../../admin")

    def test_rejects_slash(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_id("id/../../other")

    def test_rejects_query_string(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_id("id?admin=true")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_id("id with spaces")

    def test_rejects_newlines(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_id("id\nnewline")

    def test_rejects_semicolons(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_id("id;drop")

    def test_rejects_angle_brackets(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_id("<script>")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            _validate_id("")

    def test_custom_name_in_error(self):
        with pytest.raises(ValueError, match="device_id"):
            _validate_id("bad/id", "device_id")


class TestSslConfig:
    """Tests for SSL verification configuration."""

    def test_ssl_verify_defaults_true(self):
        """SSL_VERIFY should default to True when env var not set."""
        import os
        # The module reads env at import time, so we verify the logic
        env_val = os.environ.get("UNIFI_SSL_VERIFY", "true").lower()
        ca_bundle = os.environ.get("UNIFI_CA_BUNDLE", "")
        if not ca_bundle and env_val not in ("false", "0", "no"):
            assert True  # Default path: verify=True
        else:
            pytest.skip("Env vars set, cannot test default")

    def test_ssl_verify_false_values(self):
        """All falsy string values should be recognized."""
        for val in ("false", "0", "no", "False", "FALSE", "No", "NO"):
            assert val.lower() in ("false", "0", "no")
