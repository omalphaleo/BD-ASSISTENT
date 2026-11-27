"""Tests for login throttling (A9): failure limits per account and per client address.

Needed because the limits are the only defence against password guessing: they must block
at the configured counts, expire with the window, reset an account on success, never reveal
a block to the client, and never count their own throttled rows. Runs on real PostgreSQL;
time is moved with the test clock offset, not by sleeping.
"""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from csrf_client import CsrfTestClient
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.services import AuditAction
from app.config import Settings, get_settings
from app.core import services
from app.core.clock import reset_offset, set_offset
from app.core.login_throttle import LoginThrottleLimits
from app.core.models import User, UserRole, UserSession
from app.core.passwords import hash_password
from app.db import get_session
from app.main import app as fastapi_app

PASSWORD = "correct-horse-battery"
# Hashing is deliberately slow, so every user in this module shares one hash.
PASSWORD_HASH = hash_password(PASSWORD)
WRONG_PASSWORD = "not-the-password"
IP_A = "203.0.113.10"
IP_B = "203.0.113.20"
UNUSED_DATABASE_URL = "postgresql+psycopg://user:pw@localhost:5432/unused"
EXPECTED_401_BODY = b'{"detail":"Invalid email or password"}'


@pytest.fixture(autouse=True)
def _reset_clock_offset() -> Iterator[None]:
    """Reset the process-wide clock offset around each test so one test cannot shift another."""
    reset_offset()
    yield
    reset_offset()


def _make_user(db_session: Session, email: str) -> User:
    """Insert an active synthetic user who knows PASSWORD."""
    new_user = User(email=email, password_hash=PASSWORD_HASH, role=UserRole.REP)
    db_session.add(new_user)
    db_session.flush()
    return new_user


@pytest.fixture
def alice(db_session: Session) -> User:
    """The user whose account the tests attack."""
    return _make_user(db_session, "alice@example.com")


@pytest.fixture
def bob(db_session: Session) -> User:
    """A second user, to prove limits on one account do not affect another."""
    return _make_user(db_session, "bob@example.com")


def _attempt(
    db_session: Session,
    email: str = "alice@example.com",
    password: str = PASSWORD,
    ip: str = IP_A,
    limits: LoginThrottleLimits | None = None,
) -> str | None:
    """Call services.login; return the token on success or None if it raised the login error."""
    try:
        token, _ = services.login(
            db_session, email, password, ip_address=ip, throttle_limits=limits
        )
    except services.InvalidCredentialsError:
        return None
    return token


def _fail(db_session: Session, times: int, **kwargs: object) -> None:
    """Make `times` failed attempts with a wrong password."""
    for _ in range(times):
        assert _attempt(db_session, password=WRONG_PASSWORD, **kwargs) is None


def _count_action(db_session: Session, action: AuditAction) -> int:
    """Count audit rows of one action."""
    return db_session.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == action.value)
    ).scalar_one()


def test_account_is_blocked_after_five_failures_even_with_the_correct_password(
    db_session: Session, alice: User
) -> None:
    """5 wrong passwords block the account: the 6th, correct attempt fails and no session starts."""
    _fail(db_session, 5)

    assert _attempt(db_session) is None
    assert db_session.execute(select(func.count()).select_from(UserSession)).scalar_one() == 0
    throttled = db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_THROTTLED.value)
    ).scalar_one()
    assert throttled.actor_user_id == alice.id
    assert throttled.summary == {"scope": "account"}
    assert throttled.ip_address == IP_A


def test_four_failures_do_not_block(db_session: Session, alice: User) -> None:
    """Below the limit (4 failures) the correct password still logs in."""
    _fail(db_session, 4)

    assert _attempt(db_session) is not None


def test_throttled_attempts_are_not_counted_as_failures(db_session: Session, alice: User) -> None:
    """Blocked attempts write auth.login_throttled and leave the failure count at 5."""
    _fail(db_session, 5)

    for _ in range(3):
        assert _attempt(db_session) is None

    assert _count_action(db_session, AuditAction.LOGIN_FAILED) == 5
    assert _count_action(db_session, AuditAction.LOGIN_THROTTLED) == 3


def test_block_ends_when_the_window_passes(db_session: Session, alice: User) -> None:
    """After 15 minutes on the test clock the old failures are outside the window: login works."""
    _fail(db_session, 5)
    assert _attempt(db_session) is None

    set_offset(timedelta(minutes=15, seconds=1))

    assert _attempt(db_session) is not None


def test_success_resets_the_account_failures(db_session: Session, alice: User) -> None:
    """4 failures, a success, then 4 more failures: still not blocked (count restarts)."""
    _fail(db_session, 4)
    assert _attempt(db_session) is not None
    _fail(db_session, 4)

    assert _attempt(db_session) is not None


def test_account_failures_do_not_block_another_account(
    db_session: Session, alice: User, bob: User
) -> None:
    """Five failures on alice from one address leave bob (from another address) able to log in."""
    _fail(db_session, 5)

    assert _attempt(db_session, email="bob@example.com", ip=IP_B) is not None


def test_address_limit_blocks_every_account_from_that_address(
    db_session: Session, alice: User, bob: User
) -> None:
    """With an address limit of 3, 3 failures block any login from it; another address is fine."""
    limits = LoginThrottleLimits(max_failures_per_ip=3)
    _fail(db_session, 2, limits=limits)
    _fail(db_session, 1, email="bob@example.com", limits=limits)

    assert _attempt(db_session, limits=limits) is None
    assert _attempt(db_session, email="bob@example.com", limits=limits) is None
    throttled = db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_THROTTLED.value).limit(1)
    ).scalar_one()
    assert throttled.summary == {"scope": "ip"}
    assert _attempt(db_session, ip=IP_B, limits=limits) is not None


def test_unknown_emails_are_limited_by_address_only(db_session: Session, alice: User) -> None:
    """Failures for unknown emails fill the address limit; the blocked row has no actor."""
    limits = LoginThrottleLimits(max_failures_per_ip=3)
    for index in range(3):
        assert _attempt(db_session, email=f"ghost{index}@example.com", limits=limits) is None

    assert _attempt(db_session, email="ghost9@example.com", limits=limits) is None
    throttled = db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_THROTTLED.value)
    ).scalar_one()
    assert throttled.actor_user_id is None
    assert throttled.summary == {"scope": "ip"}


def test_success_does_not_reset_the_address_count(db_session: Session, alice: User) -> None:
    """Address count is a strict rolling window: a success between failures does not clear it."""
    limits = LoginThrottleLimits(max_failures_per_ip=3)
    _fail(db_session, 2, limits=limits)
    assert _attempt(db_session, limits=limits) is not None
    _fail(db_session, 1, limits=limits)

    assert _attempt(db_session, limits=limits) is None


def test_successful_login_writes_an_audit_row_without_secrets(
    db_session: Session, alice: User
) -> None:
    """A successful login records auth.login_succeeded with actor and address, no summary."""
    assert _attempt(db_session) is not None

    row = db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_SUCCEEDED.value)
    ).scalar_one()
    assert row.actor_user_id == alice.id
    assert row.ip_address == IP_A
    assert row.summary is None


def test_blocked_http_login_looks_like_a_wrong_password(db_session: Session, alice: User) -> None:
    """Over HTTP a blocked correct password gets the same 401 body and no cookie."""

    def override_get_session() -> Iterator[Session]:
        """Hand the test's rolled-back session to the request."""
        yield db_session

    settings = Settings(
        _env_file=None, database_url=UNUSED_DATABASE_URL, session_cookie_secure=False
    )
    fastapi_app.dependency_overrides[get_session] = override_get_session
    fastapi_app.dependency_overrides[get_settings] = lambda: settings
    try:
        client: TestClient = CsrfTestClient(fastapi_app)
        credentials = {"email": "alice@example.com", "password": WRONG_PASSWORD}
        responses = [client.post("/auth/login", json=credentials) for _ in range(5)]
        blocked = client.post(
            "/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
        )
    finally:
        fastapi_app.dependency_overrides.clear()

    assert {response.content for response in responses} == {EXPECTED_401_BODY}
    assert blocked.status_code == 401
    assert blocked.content == EXPECTED_401_BODY
    assert "set-cookie" not in blocked.headers
    assert _count_action(db_session, AuditAction.LOGIN_THROTTLED) == 1


def test_throttle_settings_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults are 5 / 20 / 15 minutes; environment variables override them."""
    defaults = Settings(_env_file=None, database_url=UNUSED_DATABASE_URL)
    assert LoginThrottleLimits.from_settings(defaults) == LoginThrottleLimits(
        5, 20, timedelta(minutes=15)
    )

    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_ACCOUNT", "3")
    monkeypatch.setenv("LOGIN_MAX_FAILURES_PER_IP", "7")
    monkeypatch.setenv("LOGIN_THROTTLE_WINDOW_MINUTES", "30")
    custom = Settings(_env_file=None, database_url=UNUSED_DATABASE_URL)
    assert LoginThrottleLimits.from_settings(custom) == LoginThrottleLimits(
        3, 7, timedelta(minutes=30)
    )


@pytest.mark.parametrize(
    "name",
    [
        "LOGIN_MAX_FAILURES_PER_ACCOUNT",
        "LOGIN_MAX_FAILURES_PER_IP",
        "LOGIN_THROTTLE_WINDOW_MINUTES",
    ],
)
def test_non_positive_throttle_setting_is_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """A zero limit or window would lock everyone out (or never block): Settings refuses it."""
    monkeypatch.setenv(name, "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=UNUSED_DATABASE_URL)
