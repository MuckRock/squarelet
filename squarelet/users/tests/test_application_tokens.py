# Django
from django.utils import timezone

# Standard Library
from datetime import timedelta

# Third Party
import pytest

# Squarelet
from squarelet.users.models import ApplicationToken


@pytest.mark.django_db()
class TestApplicationTokenModel:
    """Model-level behavior for user-owned application tokens"""

    def test_generate_returns_namespaced_plaintext(self, user_factory):
        user = user_factory()
        token, plaintext = ApplicationToken.generate(user, "my script")
        assert plaintext.startswith(f"mr_{token.prefix}_")
        assert token.user == user
        assert token.name == "my script"
        assert token.expires_at is None
        assert token.allow_staff is False

    def test_plaintext_is_not_stored(self, user_factory):
        token, plaintext = ApplicationToken.generate(user_factory(), "script")
        secret = plaintext.split("_", 2)[2]
        token.refresh_from_db()
        for value in (token.prefix, token.hashed_secret, token.name):
            assert secret not in value

    def test_authenticate_round_trip(self, user_factory):
        token, plaintext = ApplicationToken.generate(user_factory(), "script")
        assert token.last_used_at is None
        assert ApplicationToken.authenticate(plaintext) == token
        token.refresh_from_db()
        assert token.last_used_at is not None

    @pytest.mark.parametrize(
        "plaintext",
        ["", "garbage", "mr_nope", "mr_abc_def", "xx_abc_def_ghi"],
    )
    def test_authenticate_malformed(self, plaintext):
        assert ApplicationToken.authenticate(plaintext) is None

    def test_authenticate_wrong_secret(self, user_factory):
        token, _plaintext = ApplicationToken.generate(user_factory(), "script")
        assert ApplicationToken.authenticate(f"mr_{token.prefix}_wrong") is None

    def test_authenticate_revoked(self, user_factory):
        token, plaintext = ApplicationToken.generate(user_factory(), "script")
        token.revoke()
        assert token.revoked_at is not None
        assert not token.is_active
        assert ApplicationToken.authenticate(plaintext) is None

    def test_authenticate_expired(self, user_factory):
        token, plaintext = ApplicationToken.generate(
            user_factory(), "script", expires_in=ApplicationToken.Expiry.WEEK
        )
        token.expires_at = timezone.now() - timedelta(seconds=1)
        token.save()
        assert not token.is_active
        assert ApplicationToken.authenticate(plaintext) is None

    def test_authenticate_inactive_user(self, user_factory):
        _token, plaintext = ApplicationToken.generate(
            user_factory(is_active=False), "script"
        )
        assert ApplicationToken.authenticate(plaintext) is None

    @pytest.mark.freeze_time("2026-01-15 12:00:00")
    @pytest.mark.parametrize(
        "expires_in,days",
        [
            (ApplicationToken.Expiry.WEEK, 7),
            (ApplicationToken.Expiry.MONTH, 30),
            (ApplicationToken.Expiry.QUARTER, 90),
            (ApplicationToken.Expiry.YEAR, 365),
        ],
    )
    def test_generate_expiration_date(self, user_factory, expires_in, days):
        token, _plaintext = ApplicationToken.generate(
            user_factory(), "script", expires_in=expires_in
        )
        assert token.expires_in == days
        assert token.expires_at == timezone.now() + timedelta(days=days)

    def test_rotate(self, user_factory):
        old, old_plaintext = ApplicationToken.generate(
            user_factory(),
            "script",
            expires_in=ApplicationToken.Expiry.MONTH,
            allow_staff=True,
        )
        new, new_plaintext = old.rotate()
        old.refresh_from_db()
        assert not old.is_active
        assert new.is_active
        assert new.pk != old.pk
        assert new_plaintext != old_plaintext
        assert (new.user, new.name, new.allow_staff, new.expires_in) == (
            old.user,
            old.name,
            old.allow_staff,
            old.expires_in,
        )
        assert ApplicationToken.authenticate(old_plaintext) is None
        assert ApplicationToken.authenticate(new_plaintext) == new

    def test_log_label(self, user_factory):
        token, _plaintext = ApplicationToken.generate(
            user_factory(username="alice"), "nightly scraper"
        )
        assert token.log_label == "alice:nightly scraper"

    def test_active_queryset(self, user_factory):
        user = user_factory()
        active, _ = ApplicationToken.generate(user, "active")
        revoked, _ = ApplicationToken.generate(user, "revoked")
        revoked.revoke()
        expired, _ = ApplicationToken.generate(user, "expired", expires_in=7)
        expired.expires_at = timezone.now() - timedelta(days=1)
        expired.save()
        assert list(user.application_tokens.active()) == [active]

    def test_factory_exposes_plaintext(self, application_token_factory):
        token = application_token_factory()
        assert ApplicationToken.authenticate(token.plaintext) == token
