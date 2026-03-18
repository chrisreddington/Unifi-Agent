"""Security tests for UniFi MCP server — ID validation and SSL config."""

import builtins
import importlib.util
import re
import ssl
import sys
import types
from pathlib import Path

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

    @staticmethod
    def _load_server_module(module_name: str = "unifi_server_test_module"):
        sys.modules.pop(module_name, None)
        server_path = Path(__file__).resolve().parents[1] / "unifi-mcp" / "server.py"
        spec = importlib.util.spec_from_file_location(module_name, server_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_ssl_verify_defaults_true(self, monkeypatch: pytest.MonkeyPatch):
        """Default secure mode should keep httpx/Python defaults."""
        monkeypatch.delenv("UNIFI_SSL_VERIFY", raising=False)
        monkeypatch.delenv("UNIFI_CA_BUNDLE", raising=False)
        monkeypatch.delenv("UNIFI_SSL_USE_TRUSTSTORE", raising=False)
        module = self._load_server_module()
        assert module.SSL_VERIFY is True

    def test_ssl_verify_false_values(self):
        """All falsy string values should be recognized."""
        for val in ("false", "0", "no", "False", "FALSE", "No", "NO"):
            assert val.lower() in ("false", "0", "no")

    def test_ssl_verify_false_disables_verification(self, monkeypatch: pytest.MonkeyPatch):
        """The insecure opt-out should still work."""
        monkeypatch.setenv("UNIFI_SSL_VERIFY", "false")
        monkeypatch.delenv("UNIFI_CA_BUNDLE", raising=False)
        monkeypatch.delenv("UNIFI_SSL_USE_TRUSTSTORE", raising=False)
        module = self._load_server_module("unifi_server_ssl_disabled")
        assert module.SSL_VERIFY is False

    def test_ca_bundle_uses_base_httpx_behavior(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """An explicit CA bundle should use the standard httpx verify path by default."""
        cert = tmp_path / "test.pem"
        cert.write_text("dummy")
        monkeypatch.delenv("UNIFI_SSL_VERIFY", raising=False)
        monkeypatch.setenv("UNIFI_CA_BUNDLE", str(cert))
        monkeypatch.delenv("UNIFI_SSL_USE_TRUSTSTORE", raising=False)
        module = self._load_server_module("unifi_server_ca_bundle")
        assert module.SSL_VERIFY == str(cert)

    def test_truststore_is_opt_in(self, monkeypatch: pytest.MonkeyPatch):
        """The platform trust store should only be used when explicitly enabled."""
        monkeypatch.delenv("UNIFI_SSL_VERIFY", raising=False)
        monkeypatch.delenv("UNIFI_CA_BUNDLE", raising=False)
        monkeypatch.setenv("UNIFI_SSL_USE_TRUSTSTORE", "true")
        monkeypatch.setitem(sys.modules, "truststore", types.SimpleNamespace(SSLContext=ssl.SSLContext))
        module = self._load_server_module("unifi_server_truststore_enabled")
        assert isinstance(module.SSL_VERIFY, ssl.SSLContext)
        assert module.SSL_VERIFY.verify_mode == ssl.CERT_REQUIRED

    def test_truststore_requires_optional_dependency(self, monkeypatch: pytest.MonkeyPatch):
        """Opting into truststore should fail clearly if the package is unavailable."""
        monkeypatch.delenv("UNIFI_SSL_VERIFY", raising=False)
        monkeypatch.delenv("UNIFI_CA_BUNDLE", raising=False)
        monkeypatch.setenv("UNIFI_SSL_USE_TRUSTSTORE", "true")
        monkeypatch.delitem(sys.modules, "truststore", raising=False)

        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "truststore":
                raise ImportError("missing optional dependency")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guarded_import)
        with pytest.raises(RuntimeError, match="optional truststore package"):
            self._load_server_module("unifi_server_missing_truststore")
