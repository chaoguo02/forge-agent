from __future__ import annotations

import pytest

from server.main import validate_bind_host


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "[::1]", "localhost"])
def test_loopback_bind_is_allowed_without_remote_opt_in(host):
    assert validate_bind_host(host, allow_remote=False) is False


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.test"])
def test_remote_bind_requires_explicit_opt_in(host):
    with pytest.raises(ValueError, match="--allow-remote"):
        validate_bind_host(host, allow_remote=False)


def test_remote_bind_reports_warning_requirement_when_explicitly_allowed():
    assert validate_bind_host("0.0.0.0", allow_remote=True) is True
