"""Bound unauthenticated login inputs before Redis and scrypt work."""
import pytest
from pydantic import ValidationError

from app.auth import Credentials as ParentCredentials
from app.staff_auth import Credentials as StaffCredentials


@pytest.mark.parametrize("credentials", [ParentCredentials, StaffCredentials])
def test_login_accepts_normal_credentials(credentials):
    value = credentials(username="school_user", password="correct-horse-battery")
    assert value.username == "school_user"


@pytest.mark.parametrize("credentials", [ParentCredentials, StaffCredentials])
@pytest.mark.parametrize("field,value", [
    ("username", ""),
    ("username", "u" * 81),
    ("password", ""),
    ("password", "p" * 129),
])
def test_login_rejects_invalid_lengths(credentials, field, value):
    payload = {"username": "school_user", "password": "test-password"}
    payload[field] = value
    with pytest.raises(ValidationError):
        credentials(**payload)


@pytest.mark.parametrize("school_code", ["", "s" * 81])
def test_parent_login_rejects_invalid_school_code_length(school_code):
    with pytest.raises(ValidationError):
        ParentCredentials(username="school_user", password="test-password", school_code=school_code)
