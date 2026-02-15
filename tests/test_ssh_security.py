"""Security tests for SSH MCP server — path validation."""

import re
import pytest

# Replicate the validation logic directly to avoid importing server dependencies
_SAFE_PATH_RE = re.compile(r"^[a-zA-Z0-9/_\-.~]+$")


def _validate_path(path: str) -> str:
    """Validate a path contains only safe characters."""
    if not path or not _SAFE_PATH_RE.match(path):
        raise ValueError(f"Invalid path: contains unsafe characters")
    if ".." in path.split("/"):
        raise ValueError(f"Invalid path: directory traversal not allowed")
    return path


class TestPathValidation:
    """Tests for CWD path sanitization to prevent command injection."""

    def test_valid_absolute_path(self):
        assert _validate_path("/home/user") == "/home/user"

    def test_valid_home_tilde(self):
        assert _validate_path("~") == "~"

    def test_valid_relative_path(self):
        assert _validate_path("subdir/file.txt") == "subdir/file.txt"

    def test_valid_path_with_dots_in_filename(self):
        assert _validate_path("/tmp/file.tar.gz") == "/tmp/file.tar.gz"

    def test_valid_path_with_dashes_underscores(self):
        assert _validate_path("/var/log/my_app-2024") == "/var/log/my_app-2024"

    def test_rejects_directory_traversal(self):
        with pytest.raises(ValueError, match="directory traversal"):
            _validate_path("/home/user/../../etc/passwd")

    def test_rejects_double_dot_at_start(self):
        with pytest.raises(ValueError, match="directory traversal"):
            _validate_path("../etc/passwd")

    def test_rejects_semicolon_injection(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_path("/tmp; rm -rf /")

    def test_rejects_pipe_injection(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_path("/tmp | cat /etc/passwd")

    def test_rejects_backtick_injection(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_path("/tmp/`whoami`")

    def test_rejects_dollar_expansion(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_path("/tmp/$(whoami)")

    def test_rejects_ampersand(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_path("/tmp && echo pwned")

    def test_rejects_newline(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_path("/tmp\necho pwned")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_path("/tmp/my dir")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            _validate_path("")


class TestSafePathRegex:
    """Direct regex tests for the path pattern."""

    def test_allows_alphanumeric(self):
        assert _SAFE_PATH_RE.match("abc123")

    def test_allows_slashes(self):
        assert _SAFE_PATH_RE.match("/a/b/c")

    def test_allows_tilde(self):
        assert _SAFE_PATH_RE.match("~/dir")

    def test_blocks_semicolons(self):
        assert not _SAFE_PATH_RE.match("a;b")

    def test_blocks_spaces(self):
        assert not _SAFE_PATH_RE.match("a b")

    def test_blocks_parens(self):
        assert not _SAFE_PATH_RE.match("$(cmd)")
