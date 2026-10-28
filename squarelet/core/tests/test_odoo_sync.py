# Django
from django.core import mail
from django.core.management import call_command
from django.test import override_settings

# Standard Library
import logging
from datetime import date
from unittest.mock import Mock, patch

# Third Party
import pytest
import requests

# Squarelet
from squarelet.core.management.commands import sync_odoo
from squarelet.organizations.tests.factories import OrganizationFactory, PlanFactory

# pylint:disable=protected-access,too-many-lines

ESSENTIAL_ID = 9
ENTERPRISE_ID = 10


@pytest.fixture(autouse=True)
def tier_caches():
    """The tier caches are module-global; seed two tiers and reset around every test."""
    sync_odoo._TIER_ID_CACHE.clear()
    sync_odoo._TIER_SLUG_BY_ID.clear()
    sync_odoo._TIER_ID_CACHE.update(
        {"sunlight-essential": ESSENTIAL_ID, "sunlight-enterprise": ENTERPRISE_ID}
    )
    sync_odoo._TIER_SLUG_BY_ID.update(
        {ESSENTIAL_ID: "sunlight-essential", ENTERPRISE_ID: "sunlight-enterprise"}
    )
    yield
    sync_odoo._TIER_ID_CACHE.clear()
    sync_odoo._TIER_SLUG_BY_ID.clear()


def _spec(tier_slug="sunlight-essential", source=False, **overrides):
    """A desired plan-line spec as _item_spec builds it."""
    spec = {
        "tier_slug": tier_slug,
        "tier_name": "Sunlight Research Center - Essential",
        "x_source_id": source,
        "x_interval": "annual",
        "x_rate": "standard",
        "x_code": "",
        "x_renews_on": "2027-01-05",
        "x_cancelling": False,
        "wix": True,
    }
    spec.update(overrides)
    return spec


def _odoo_line(line_id, tier_id=ESSENTIAL_ID, source=False, **overrides):
    """A plan line as Odoo's search_read returns it, matching _spec() by default."""
    line = {
        "id": line_id,
        "x_tier_id": [
            tier_id,
            "Essential" if tier_id == ESSENTIAL_ID else "Enterprise",
        ],
        "x_source_id": source,
        "x_interval": "annual",
        "x_rate": "standard",
        "x_code": False,
        "x_renews_on": "2027-01-05",
        "x_cancelling": False,
    }
    line.update(overrides)
    return line


def _mock_plan(slug, free=False, annual=False, wix=False, name=None):
    """A Mock Plan; name is set after init since Mock(name=...) names the mock."""
    plan = Mock(slug=slug, free=free, annual=annual, wix=wix)
    plan.name = name or slug
    return plan


class TestOdooRequest:
    """_odoo_request returns parsed JSON on success and raises on failure."""

    def test_returns_json_on_success(self):
        """A successful POST returns the parsed JSON body."""
        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [{"id": 42}]
        with patch.object(sync_odoo._session, "post", return_value=resp) as post:
            result = sync_odoo._odoo_request("x_plan_line/search_read", {"domain": []})
        assert result == [{"id": 42}]
        post.assert_called_once()

    def test_raises_on_connection_error(self):
        """A transport error (retries exhausted) propagates to the caller."""
        with patch.object(
            sync_odoo._session,
            "post",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            with pytest.raises(requests.exceptions.ConnectionError):
                sync_odoo._odoo_request("x_plan_line/search_read", {"domain": []})

    def test_raises_on_bad_status(self):
        """A non-2xx response (raise_for_status) propagates as HTTPError."""
        resp = Mock(text="")
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("400")
        with patch.object(sync_odoo._session, "post", return_value=resp):
            with pytest.raises(requests.exceptions.HTTPError):
                sync_odoo._odoo_request("x_plan_line/create", {"vals_list": [{}]})

    def test_logs_response_body_on_bad_status(self, caplog):
        """The Odoo error body is logged so the cause shows in the sync report."""
        resp = Mock(text="Invalid field 'x_nope' on model 'res.partner'")
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
        with patch.object(sync_odoo._session, "post", return_value=resp):
            with caplog.at_level(logging.ERROR, logger=sync_odoo.logger.name):
                with pytest.raises(requests.exceptions.HTTPError):
                    sync_odoo._odoo_request("res.partner/search_read", {})
        assert "Invalid field 'x_nope'" in caplog.text

    def test_does_not_return_none_on_failure(self):
        """Regression guard: failure must not masquerade as 'no result'."""
        with patch.object(
            sync_odoo._session,
            "post",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            with pytest.raises(requests.exceptions.RequestException):
                sync_odoo._odoo_request("x_plan_line/search_read", {"domain": []})


class TestOdooSearch:
    """odoo_search passes limit/offset through and coerces None to []."""

    def test_passes_offset_through(self):
        """A supplied offset is included in the search_read payload."""
        with patch.object(sync_odoo, "_odoo_request", return_value=[]) as req:
            sync_odoo.odoo_search("res.partner", [["id", "=", 1]], ["id"], offset=50)
        req.assert_called_once_with(
            "res.partner/search_read",
            {"domain": [["id", "=", 1]], "fields": ["id"], "limit": 1, "offset": 50},
        )

    def test_defaults_offset_zero(self):
        """Omitting offset defaults it to 0 in the payload."""
        with patch.object(sync_odoo, "_odoo_request", return_value=[{"id": 1}]) as req:
            sync_odoo.odoo_search("res.partner", [], ["id"])
        assert req.call_args.args[1]["offset"] == 0

    def test_returns_empty_list_when_request_returns_none(self):
        """A None response body is coerced to an empty list."""
        with patch.object(sync_odoo, "_odoo_request", return_value=None):
            assert sync_odoo.odoo_search("res.partner", [], ["id"]) == []


class TestOdooSearchAll:
    """odoo_search_all pages through results and stops on a short batch."""

    def test_single_short_batch_stops(self):
        """A first batch smaller than the page size ends paging in one call."""
        with patch.object(sync_odoo, "odoo_search", return_value=[{"id": 1}]) as s:
            result = sync_odoo.odoo_search_all("res.partner", [], ["id"], page_size=200)
        assert result == [{"id": 1}]
        assert s.call_count == 1

    def test_pages_until_short_batch(self):
        """A full page followed by a short page concatenates and stops."""
        full = [{"id": i} for i in range(200)]
        with patch.object(
            sync_odoo, "odoo_search", side_effect=[full, [{"id": 200}]]
        ) as s:
            result = sync_odoo.odoo_search_all("res.partner", [], ["id"], page_size=200)
        assert len(result) == 201
        assert s.call_count == 2
        assert s.call_args_list[1].kwargs["offset"] == 200

    def test_empty_returns_empty(self):
        """No matching rows returns an empty list in a single call."""
        with patch.object(sync_odoo, "odoo_search", return_value=[]) as s:
            result = sync_odoo.odoo_search_all("res.partner", [], ["id"], page_size=200)
        assert not result
        assert s.call_count == 1

    def test_exact_multiple_needs_extra_empty_call(self):
        """An exact page-size fill needs one extra call to confirm the end."""
        full = [{"id": i} for i in range(200)]
        with patch.object(sync_odoo, "odoo_search", side_effect=[full, []]) as s:
            result = sync_odoo.odoo_search_all("res.partner", [], ["id"], page_size=200)
        assert len(result) == 200
        assert s.call_count == 2

    def test_pages_through_multiple_full_batches(self):
        """Two full pages then a short one — offset must advance each time."""
        p1 = [{"id": i} for i in range(200)]
        p2 = [{"id": i} for i in range(200, 400)]
        p3 = [{"id": 400}]
        with patch.object(sync_odoo, "odoo_search", side_effect=[p1, p2, p3]) as s:
            result = sync_odoo.odoo_search_all("res.partner", [], ["id"], page_size=200)
        assert len(result) == 401
        assert s.call_count == 3
        offsets = [c.kwargs["offset"] for c in s.call_args_list]
        assert offsets == [0, 200, 400]


class TestOdooCreateWriteUnlink:
    """odoo_create, odoo_write and odoo_unlink shape their payloads correctly."""

    def test_create_wraps_vals_in_vals_list(self):
        """A single vals dict is wrapped in the vals_list the API expects."""
        with patch.object(sync_odoo, "_odoo_request", return_value=[7]) as req:
            result = sync_odoo.odoo_create("x_plan_tier", {"x_name": "Pro"})
        assert result == [7]
        req.assert_called_once_with(
            "x_plan_tier/create", {"vals_list": [{"x_name": "Pro"}]}
        )

    def test_write_passes_ids_and_vals(self):
        """ids and vals are forwarded to the write endpoint verbatim."""
        with patch.object(sync_odoo, "_odoo_request", return_value=True) as req:
            sync_odoo.odoo_write("res.partner", [3], {"city": "NYC"})
        req.assert_called_once_with(
            "res.partner/write", {"ids": [3], "vals": {"city": "NYC"}}
        )

    def test_unlink_passes_ids(self):
        """ids are forwarded to the unlink endpoint."""
        with patch.object(sync_odoo, "_odoo_request", return_value=True) as req:
            sync_odoo.odoo_unlink("x_plan_line", [4, 5])
        req.assert_called_once_with("x_plan_line/unlink", {"ids": [4, 5]})


class TestM2o:
    """_m2o_id and _m2o_name read Odoo many2one values in any shape."""

    def test_pair(self):
        """An [id, name] pair yields its id and name."""
        assert sync_odoo._m2o_id([3, "RNN"]) == 3
        assert sync_odoo._m2o_name([3, "RNN"]) == "RNN"

    def test_bare_id(self):
        """A bare id yields itself and no name."""
        assert sync_odoo._m2o_id(3) == 3
        assert sync_odoo._m2o_name(3) == ""

    def test_empty(self):
        """False yields False and no name."""
        assert sync_odoo._m2o_id(False) is False
        assert sync_odoo._m2o_name(False) == ""


class TestLoadTiers:
    """_load_tiers fills both tier caches from Odoo."""

    def test_fills_both_directions(self):
        """Each tier is cached by slug and by id."""
        sync_odoo._TIER_ID_CACHE.clear()
        sync_odoo._TIER_SLUG_BY_ID.clear()
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=[{"id": 3, "x_slug": "pro"}]
        ):
            sync_odoo._load_tiers()
        assert sync_odoo._TIER_ID_CACHE["pro"] == 3
        assert sync_odoo._TIER_SLUG_BY_ID[3] == "pro"


@pytest.mark.django_db
class TestResolveTierId:
    """_resolve_tier_id returns cached tiers and creates missing ones."""

    def test_cached_tier_not_created(self):
        """A cached slug returns its id without creating anything."""
        with patch.object(sync_odoo, "odoo_create") as create:
            assert sync_odoo._resolve_tier_id("sunlight-essential", "x") == ESSENTIAL_ID
        create.assert_not_called()

    def test_creates_with_accounts_plan_name(self):
        """A missing tier is created named after the matching Accounts plan."""
        PlanFactory(name="Organization", slug="organization")
        with patch.object(sync_odoo, "odoo_create", return_value=[77]) as create:
            assert sync_odoo._resolve_tier_id("organization", "fallback") == 77
        create.assert_called_once_with(
            "x_plan_tier", {"x_name": "Organization", "x_slug": "organization"}
        )
        assert sync_odoo._TIER_SLUG_BY_ID[77] == "organization"

    def test_falls_back_to_given_name(self):
        """With no Accounts plan for the slug, the fallback name is used."""
        with patch.object(sync_odoo, "odoo_create", return_value=[78]) as create:
            sync_odoo._resolve_tier_id("no-such-plan", "Fallback Name")
        assert create.call_args.args[1]["x_name"] == "Fallback Name"

    def test_failed_create_returns_none(self):
        """A create that returns nothing yields None and caches nothing."""
        with patch.object(sync_odoo, "odoo_create", return_value=[]):
            assert sync_odoo._resolve_tier_id("no-such-plan", "x") is None
        assert "no-such-plan" not in sync_odoo._TIER_ID_CACHE


class TestTierFor:
    """_tier_for maps legacy plans to (tier, interval, rate)."""

    def test_mapped_slug_uses_legacy_map(self):
        """A slug in LEGACY_PLAN_MAP takes its mapped tier, interval and rate."""
        plan = _mock_plan("sunlight-essential-annual", annual=True)
        assert sync_odoo._tier_for(plan, True) == (
            "sunlight-essential",
            "annual",
            "standard",
        )

    def test_unmapped_annual_slug_is_stripped(self):
        """An unmapped -annual slug lands on its base tier, annual interval."""
        plan = _mock_plan("sunlight-basic-annual", annual=True)
        assert sync_odoo._tier_for(plan, True) == (
            "sunlight-basic",
            "annual",
            "standard",
        )

    def test_unmapped_nonprofit_slug(self):
        """An unmapped nonprofit slug drops 'nonprofit-' and rates nonprofit."""
        plan = _mock_plan("sunlight-nonprofit-widget")
        assert sync_odoo._tier_for(plan, True) == (
            "sunlight-widget",
            "monthly",
            "nonprofit",
        )

    def test_unmapped_free_plan_is_comped(self):
        """An unmapped free plan rates comped."""
        plan = _mock_plan("premium-org-comp-election-hub", free=True)
        assert sync_odoo._tier_for(plan, False) == (
            "premium-org-comp-election-hub",
            "monthly",
            "comped",
        )


class TestItemSpec:
    """_item_spec builds a plan-line spec from a SubscriptionItem."""

    def _item(self, plan_price=None, **sub):
        subscription = Mock(
            subscription_id=sub.get("subscription_id", "sub_1"),
            next_date=sub.get("next_date", date(2026, 12, 1)),
            cancelled=sub.get("cancelled", False),
            kind=sub.get("kind", "renewing"),
        )
        item = Mock(subscription=subscription, ends_on=sub.get("ends_on"))
        item.plan = _mock_plan(
            "sunlight-nonprofit-essential-annual",
            annual=True,
            wix=True,
            name="Sunlight Research Center - Essential (Annual, Non-Profit)",
        )
        item.plan_price_id = 3 if plan_price else None
        item.plan_price = plan_price
        return item

    def test_reads_plan_price_when_present(self):
        """With a PlanPrice, tier, interval, rate and code come from it."""
        price = Mock(interval="monthly", label="comped", code="legacy-basic")
        price.plan = _mock_plan(
            "sunlight-essential", name="Sunlight Research Center - Essential"
        )
        spec = sync_odoo._item_spec(self._item(plan_price=price))
        assert spec["tier_slug"] == "sunlight-essential"
        assert spec["tier_name"] == "Sunlight Research Center - Essential"
        assert spec["x_interval"] == "monthly"
        assert spec["x_rate"] == "comped"
        assert spec["x_code"] == "legacy-basic"
        assert spec["x_source_id"] is False

    def test_falls_back_to_legacy_map(self):
        """Without a PlanPrice, the legacy slug is mapped and the name trimmed."""
        spec = sync_odoo._item_spec(self._item())
        assert spec["tier_slug"] == "sunlight-essential"
        assert spec["tier_name"] == "Sunlight Research Center - Essential"
        assert spec["x_interval"] == "annual"
        assert spec["x_rate"] == "nonprofit"
        assert spec["x_code"] == ""
        assert spec["wix"] is True

    def test_renews_on_from_subscription(self):
        """Renews On is the subscription's next date as an ISO string."""
        assert sync_odoo._item_spec(self._item())["x_renews_on"] == "2026-12-01"

    def test_ends_on_wins_over_next_date(self):
        """A free line's ends_on takes precedence over the subscription date."""
        spec = sync_odoo._item_spec(self._item(ends_on=date(2026, 6, 30)))
        assert spec["x_renews_on"] == "2026-06-30"

    def test_no_date_is_false(self):
        """With no date at all, Renews On is False."""
        spec = sync_odoo._item_spec(self._item(next_date=None))
        assert spec["x_renews_on"] is False

    def test_cancelling_renewing_subscription(self):
        """A cancelled renewing subscription is cancelling."""
        spec = sync_odoo._item_spec(self._item(cancelled=True, kind="renewing"))
        assert spec["x_cancelling"] is True

    def test_one_off_is_not_cancelling(self):
        """A one-off subscription is flagged cancelled at purchase, not cancelling."""
        spec = sync_odoo._item_spec(self._item(cancelled=True, kind="one_off"))
        assert spec["x_cancelling"] is False


class TestMemberCopies:
    """_member_copies sources the org's own lines from the org."""

    def test_own_lines_sourced_from_org(self):
        """An unsourced org line is copied with the org as its source."""
        copies = sync_odoo._member_copies([_spec()], 55)
        assert copies[0]["x_source_id"] == 55

    def test_inherited_lines_keep_source(self):
        """A line inherited from a collaborative keeps that source."""
        copies = sync_odoo._member_copies([_spec(source=230)], 55)
        assert copies[0]["x_source_id"] == 230

    def test_originals_untouched(self):
        """Copying never mutates the org's own specs."""
        original = _spec()
        sync_odoo._member_copies([original], 55)
        assert original["x_source_id"] is False


class TestKeys:
    """_spec_key and _line_key agree on (tier slug, source)."""

    def test_matching_keys(self):
        """A spec and the Odoo line it produced share a key."""
        spec = _spec(source=230)
        line = _odoo_line(1, source=[230, "RNN"])
        assert sync_odoo._spec_key(spec) == sync_odoo._line_key(line)

    def test_unknown_tier_has_no_slug(self):
        """A line on a tier not in the cache keys with a None slug."""
        line = _odoo_line(1, tier_id=999)
        line["x_tier_id"] = [999, "Old"]
        assert sync_odoo._line_key(line) == (None, False)


class TestSyncPlanLines:
    """_sync_plan_lines creates, updates and removes lines to match the specs."""

    def _run(self, current, specs, dry_run=False, managed_sources=None):
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=current
        ), patch.object(sync_odoo, "odoo_create") as create, patch.object(
            sync_odoo, "odoo_write"
        ) as write, patch.object(
            sync_odoo, "odoo_unlink"
        ) as unlink:
            removed = sync_odoo._sync_plan_lines(
                8, "Acme", specs, dry_run, managed_sources=managed_sources
            )
        return removed, create, write, unlink

    def test_creates_missing_line(self):
        """A spec with no matching line is created on the partner."""
        _, create, write, unlink = self._run([], [_spec()])
        vals = create.call_args.args[1]
        assert create.call_args.args[0] == "x_plan_line"
        assert vals["x_partner_id"] == 8
        assert vals["x_tier_id"] == ESSENTIAL_ID
        assert vals["x_source_id"] is False
        write.assert_not_called()
        unlink.assert_not_called()

    def test_no_change_no_write(self):
        """A line matching its spec is left alone."""
        _, create, write, unlink = self._run([_odoo_line(1)], [_spec()])
        create.assert_not_called()
        write.assert_not_called()
        unlink.assert_not_called()

    def test_updates_changed_field(self):
        """A differing field updates the existing line in place."""
        _, create, write, _ = self._run(
            [_odoo_line(1, x_rate="standard")], [_spec(x_rate="nonprofit")]
        )
        create.assert_not_called()
        assert write.call_args.args[1] == [1]
        assert write.call_args.args[2]["x_rate"] == "nonprofit"

    def test_keeps_odoo_date_when_accounts_has_none(self):
        """A spec with no Renews On leaves the date set in Odoo alone."""
        _, _, write, _ = self._run(
            [_odoo_line(1, x_renews_on="2026-11-30")], [_spec(x_renews_on=False)]
        )
        write.assert_not_called()

    def test_removes_stale_line(self):
        """A line with no matching spec is removed and its tier name returned."""
        removed, _, _, unlink = self._run([_odoo_line(1)], [])
        unlink.assert_called_once_with("x_plan_line", [1])
        assert removed == ["Essential"]

    def test_ignores_unmanaged_sources(self):
        """Lines from a source this pass doesn't
        manage are neither matched nor removed."""
        _, create, _, unlink = self._run(
            [_odoo_line(1, source=[230, "RNN"])], [_spec()], managed_sources={False}
        )
        create.assert_called_once()
        unlink.assert_not_called()

    def test_source_distinguishes_same_tier(self):
        """The same tier from two sources is two separate lines."""
        current = [_odoo_line(1), _odoo_line(2, source=[230, "RNN"])]
        _, create, write, unlink = self._run(current, [_spec(), _spec(source=230)])
        create.assert_not_called()
        write.assert_not_called()
        unlink.assert_not_called()

    def test_dry_run_never_writes(self):
        """Dry-run creates, updates and removes nothing, but reports removals."""
        current = [_odoo_line(1, x_rate="comped"), _odoo_line(2, tier_id=ENTERPRISE_ID)]
        removed, create, write, unlink = self._run(current, [_spec()], dry_run=True)
        create.assert_not_called()
        write.assert_not_called()
        unlink.assert_not_called()
        assert removed == ["Enterprise"]


class TestRemoveMemberLines:
    """_remove_member_lines deletes only lines whose key the org manages."""

    def test_removes_matching_keys_only(self):
        """Lines copied from the org go; the member's other lines stay."""
        current = [_odoo_line(1, source=[55, "Acme"]), _odoo_line(2)]
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=current
        ), patch.object(sync_odoo, "odoo_unlink") as unlink:
            count = sync_odoo._remove_member_lines(8, {("sunlight-essential", 55)})
        unlink.assert_called_once_with("x_plan_line", [1])
        assert count == 1

    def test_nothing_to_remove(self):
        """No matching lines means no unlink call."""
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=[_odoo_line(2)]
        ), patch.object(sync_odoo, "odoo_unlink") as unlink:
            assert sync_odoo._remove_member_lines(8, {("sunlight-essential", 55)}) == 0
        unlink.assert_not_called()


class TestSunlightStatus:
    """_sunlight_status confirms from the org's own wix lines only."""

    def test_confirmed_with_wix_line(self):
        """Any own wix line confirms the org."""
        assert sync_odoo._sunlight_status([_spec(wix=False), _spec()]) == "Confirmed"

    def test_none_without_wix_line(self):
        """No own wix line leaves the status unset."""
        assert sync_odoo._sunlight_status([_spec(wix=False)]) is None


class TestCollaborativeContext:
    """_collaborative_context gathers what an org inherits from its collaboratives."""

    def test_member_org(self):
        """A member org gets the collaborative's lines, tag, Odoo id and label."""
        cfg = sync_odoo.CollaborativeConfig(
            "rural-news-network", 3, {"acme"}, 230, [_spec(source=230)]
        )
        org = Mock(slug="acme")
        lines, tags, odoo_ids, labels = sync_odoo._collaborative_context(
            org, {"rural-news-network": cfg}
        )
        assert lines == [_spec(source=230)]
        assert tags == [3]
        assert odoo_ids == {230}
        assert labels == ["rural-news-network"]

    def test_non_member_org(self):
        """An org outside every collaborative inherits nothing."""
        cfg = sync_odoo.CollaborativeConfig("rural-news-network", 3, {"other"}, 230, [])
        org = Mock(slug="acme")
        assert sync_odoo._collaborative_context(org, {"rural-news-network": cfg}) == (
            [],
            [],
            set(),
            [],
        )


class TestMemberPlan:
    """_member_plan builds member copies, managed sources and keys."""

    def test_sources_and_keys(self):
        """Sources cover the org and its collaboratives; keys match the copies."""
        lines, sources, keys = sync_odoo._member_plan(
            [_spec(), _spec("sunlight-enterprise", source=230)], 55, {230}
        )
        assert sources == {55, 230}
        assert keys == {("sunlight-essential", 55), ("sunlight-enterprise", 230)}
        assert len(lines) == 2


class TestFindMember:
    """_find_member matches by account uuid, then primary email, then secondary."""

    def test_uuid_match(self):
        """A uuid hit returns its id immediately, without an email search."""
        user = Mock(uuid="u-1", email="a@b.com")
        with patch.object(sync_odoo, "odoo_search", return_value=[{"id": 2}]) as s:
            assert sync_odoo._find_member(user) == (2, False)
        assert s.call_count == 1

    def test_primary_match(self):
        """No uuid hit but a primary-email hit returns id and False."""
        user = Mock(uuid="u-1", email="a@b.com")
        with patch.object(sync_odoo, "odoo_search", side_effect=[[], [{"id": 3}]]):
            assert sync_odoo._find_member(user) == (3, False)

    def test_secondary_match(self):
        """No uuid/primary hit but a secondary hit returns id and True."""
        user = Mock(uuid="u-1", email="a@b.com")
        with patch.object(sync_odoo, "odoo_search", side_effect=[[], [], [{"id": 8}]]):
            assert sync_odoo._find_member(user) == (8, True)

    def test_no_match(self):
        """No uuid, primary, or secondary match returns (None, False)."""
        user = Mock(uuid="u-1", email="a@b.com")
        with patch.object(sync_odoo, "odoo_search", side_effect=[[], [], []]):
            assert sync_odoo._find_member(user) == (None, False)


class TestMemberVals:
    """_member_vals builds contact vals, omitting email on secondary match."""

    def _user(self):
        user = Mock()
        user.name = "Jane"
        user.email = "jane@b.com"
        user.id = 5
        user.uuid = "u-5"
        user.client_stats = {}
        return user

    def test_includes_email_by_default(self):
        """A primary/new match includes email and the parent link."""
        vals = sync_odoo._member_vals(self._user(), 1, matched_via_secondary=False)
        assert vals["email"] == "jane@b.com"
        assert vals["parent_id"] == 1

    def test_omits_email_when_matched_via_secondary(self):
        """A secondary-email match omits email to avoid clobbering the primary."""
        vals = sync_odoo._member_vals(self._user(), 1, matched_via_secondary=True)
        assert "email" not in vals

    def test_has_no_plan_field(self):
        """Plans live on plan lines now, never on the contact itself."""
        vals = sync_odoo._member_vals(self._user(), 1, matched_via_secondary=False)
        assert "x_studio_plan_1" not in vals


class TestSyncMember:
    """sync_member creates or updates the contact and returns its id."""

    def _user(self):
        user = Mock(uuid="u-5", email="jane@b.com", id=5, client_stats={})
        user.name = "Jane"
        return user

    def test_existing_member_returns_id(self):
        """An existing contact is updated and its id returned."""
        with patch.object(
            sync_odoo, "_find_member", return_value=(8, False)
        ), patch.object(sync_odoo, "_update_member") as update:
            assert sync_odoo.sync_member(self._user(), "Acme", 1) == 8
        update.assert_called_once()

    def test_new_member_created(self):
        """A new contact is created and the new id returned."""
        with patch.object(
            sync_odoo, "_find_member", return_value=(None, False)
        ), patch.object(sync_odoo, "odoo_create", return_value=[42]):
            assert sync_odoo.sync_member(self._user(), "Acme", 1) == 42

    def test_dry_run_new_member_returns_none(self):
        """In dry-run a new contact isn't created, so there is no id."""
        with patch.object(
            sync_odoo, "_find_member", return_value=(None, False)
        ), patch.object(sync_odoo, "odoo_create") as create:
            assert sync_odoo.sync_member(self._user(), "Acme", 1, dry_run=True) is None
        create.assert_not_called()


class TestUpdateMember:
    """_update_member diffs an existing member and guards parent reassignment."""

    def _current(self, **overrides):
        base = {
            "id": 8,
            "name": "Jane",
            "email": "jane@b.com",
            "parent_id": [1, "Acme"],
            "is_company": False,
            "company_type": "person",
            "x_studio_muckrock_accounts": True,
            "x_studio_muckrock_accounts_id": 5,
            "x_studio_muckrock_accounts_uuid": "u-5",
        }
        base.update(overrides)
        return base

    def _matching_vals(self):
        return {
            "name": "Jane",
            "email": "jane@b.com",
            "parent_id": 1,
            "is_company": False,
            "company_type": "person",
            "x_studio_muckrock_accounts": True,
            "x_studio_muckrock_accounts_id": 5,
            "x_studio_muckrock_accounts_uuid": "u-5",
        }

    def test_no_write_when_unchanged(self):
        """Vals matching the current Odoo row produce no write."""
        user = Mock(email="jane@b.com")
        with patch.object(
            sync_odoo, "odoo_search", return_value=[self._current()]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._update_member(user, "Acme", 8, self._matching_vals(), False)
        write.assert_not_called()

    def test_changed_field_triggers_write(self):
        """A changed field writes the contact."""
        user = Mock(email="jane@b.com")
        vals = self._matching_vals()
        vals["name"] = "Jane Doe"
        with patch.object(
            sync_odoo, "odoo_search", return_value=[self._current()]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._update_member(user, "Acme", 8, vals, False)
        assert write.call_args.args[2]["name"] == "Jane Doe"

    def test_does_not_reassign_existing_parent(self):
        """A contact already under a parent is never moved to another one."""
        user = Mock(email="jane@b.com")
        vals = self._matching_vals()
        vals["parent_id"] = 999
        with patch.object(
            sync_odoo, "odoo_search", return_value=[self._current()]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._update_member(user, "Acme", 8, vals, False)
        write.assert_not_called()

    def test_dry_run_no_write(self):
        """Dry-run performs no write even when there is a diff."""
        user = Mock(email="jane@b.com")
        vals = self._matching_vals()
        vals["name"] = "Jane Doe"
        with patch.object(
            sync_odoo, "odoo_search", return_value=[self._current()]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._update_member(user, "Acme", 8, vals, True)
        write.assert_not_called()


class TestIsDeparted:
    """_is_departed identifies members no longer in the org."""

    def test_false_without_primary_email(self):
        """A member with no primary email is never treated as departed."""
        assert sync_odoo._is_departed({"email": ""}, set()) is False

    def test_false_when_still_a_member(self):
        """A member whose primary email is in the roster is not departed."""
        member = {"email": "a@b.com", "x_studio_muckrock_accounts": True}
        assert sync_odoo._is_departed(member, {"a@b.com"}) is False

    def test_false_when_secondary_still_a_member(self):
        """A member whose secondary email is in the roster is not departed."""
        member = {
            "email": "a@b.com",
            "x_studio_secondary_email": "alt@b.com",
            "x_studio_muckrock_accounts": True,
        }
        assert sync_odoo._is_departed(member, {"alt@b.com"}) is False

    def test_false_when_never_on_accounts(self):
        """A member never synced from Accounts is skipped, not departed."""
        member = {"email": "a@b.com", "x_studio_muckrock_accounts": False}
        assert sync_odoo._is_departed(member, set()) is False

    def test_true_when_departed(self):
        """An Odoo contact still on Accounts but absent from the roster is departed."""
        member = {"email": "a@b.com", "x_studio_muckrock_accounts": True}
        assert sync_odoo._is_departed(member, {"other@b.com"}) is True


class TestUnlinkDepartedMember:
    """_unlink_departed_member clears the parent and the lines copied from the org."""

    def _org(self):
        org = Mock()
        org.name = "Acme"
        return org

    def test_clears_parent_and_removes_org_lines(self):
        """The parent is cleared and only the org's copied lines are removed."""
        member = {"id": 8, "email": "a@b.com"}
        keys = {("sunlight-essential", 55)}
        with patch.object(sync_odoo, "odoo_write") as write, patch.object(
            sync_odoo, "_remove_member_lines", return_value=1
        ) as remove:
            sync_odoo._unlink_departed_member(member, self._org(), keys, dry_run=False)
        write.assert_called_once_with("res.partner", [8], {"parent_id": False})
        remove.assert_called_once_with(8, keys)

    def test_dry_run_no_write(self):
        """Dry-run neither unlinks nor removes lines."""
        member = {"id": 8, "email": "a@b.com"}
        with patch.object(sync_odoo, "odoo_write") as write, patch.object(
            sync_odoo, "_remove_member_lines"
        ) as remove:
            sync_odoo._unlink_departed_member(member, self._org(), set(), dry_run=True)
        write.assert_not_called()
        remove.assert_not_called()


class TestFlagDepartedMember:
    """_flag_departed_member stamps today's date on a soft departure."""

    def test_writes_todays_date(self):
        """A soft departure writes today's ISO date to the departed field."""
        org = Mock()
        org.name = "Acme"
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._flag_departed_member({"id": 8, "email": "a@b.com"}, org, False)
        written = write.call_args.args[2]
        assert written["x_studio_org_departed_date"] == date.today().isoformat()

    def test_dry_run_no_write(self):
        """Dry-run performs no write."""
        org = Mock()
        org.name = "Acme"
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._flag_departed_member({"id": 8, "email": "a@b.com"}, org, True)
        write.assert_not_called()


class TestRemoveDepartedMembers:
    """remove_departed_members flags or unlinks departed members per mode."""

    def _org(self):
        org = Mock()
        org.name = "Acme"
        org.users.all.return_value = [Mock(email="stay@b.com")]
        return org

    def test_flags_when_not_removing(self):
        """With remove=False a departed member is flagged, not unlinked."""
        members = [
            {"id": 8, "email": "gone@b.com", "x_studio_org_departed_date": False}
        ]
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=members
        ), patch.object(sync_odoo, "_is_departed", return_value=True), patch.object(
            sync_odoo, "_flag_departed_member"
        ) as flag, patch.object(
            sync_odoo, "_unlink_departed_member"
        ) as unlink:
            sync_odoo.remove_departed_members(self._org(), 1, set(), remove=False)
        flag.assert_called_once()
        unlink.assert_not_called()

    def test_unlinks_when_removing(self):
        """With remove=True a departed member is unlinked with the org's line keys."""
        members = [{"id": 8, "email": "gone@b.com"}]
        keys = {("sunlight-essential", 1)}
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=members
        ), patch.object(sync_odoo, "_is_departed", return_value=True), patch.object(
            sync_odoo, "_unlink_departed_member"
        ) as unlink:
            sync_odoo.remove_departed_members(self._org(), 1, keys, remove=True)
        assert unlink.call_args.args[2] == keys

    def test_skips_non_departed(self):
        """A member still in the org triggers neither flag nor unlink."""
        members = [{"id": 8, "email": "stay@b.com"}]
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=members
        ), patch.object(sync_odoo, "_is_departed", return_value=False), patch.object(
            sync_odoo, "_flag_departed_member"
        ) as flag:
            sync_odoo.remove_departed_members(self._org(), 1, set(), remove=False)
        flag.assert_not_called()


class TestSyncIndividual:
    """_sync_individual writes an individual subscriber's own lines to their contact."""

    def _org(self):
        org = Mock()
        org.user = Mock(email="pro@b.com")
        return org

    def _patches(self, found):
        return (
            patch.object(sync_odoo, "_org_item_specs", return_value=[_spec()]),
            patch.object(sync_odoo, "_find_member", return_value=found),
            patch.object(
                sync_odoo, "_member_vals", return_value={"parent_id": None, "name": "P"}
            ),
        )

    def test_existing_contact_gets_personal_lines(self):
        """An existing contact is updated and only its unsourced lines are managed."""
        specs, find, vals = self._patches((8, False))
        with specs, find, vals, patch.object(
            sync_odoo, "_update_member"
        ) as update, patch.object(sync_odoo, "_sync_plan_lines") as lines:
            assert sync_odoo._sync_individual(self._org(), dry_run=False) == 8
        assert "parent_id" not in update.call_args.args[3]
        lines.assert_called_once_with(
            8, "pro@b.com", [_spec()], False, managed_sources={False}
        )

    def test_new_contact_created_without_parent(self):
        """A new individual contact is created with no parent org."""
        specs, find, vals = self._patches((None, False))
        with specs, find, vals, patch.object(
            sync_odoo, "odoo_create", return_value=[42]
        ) as create, patch.object(sync_odoo, "_sync_plan_lines") as lines:
            assert sync_odoo._sync_individual(self._org(), dry_run=False) == 42
        assert "parent_id" not in create.call_args.args[1]
        assert lines.call_args.args[0] == 42

    def test_dry_run_new_contact_skips_lines(self):
        """In dry-run a new individual isn't created and has no lines to sync."""
        specs, find, vals = self._patches((None, False))
        with specs, find, vals, patch.object(
            sync_odoo, "odoo_create"
        ) as create, patch.object(sync_odoo, "_sync_plan_lines") as lines:
            assert sync_odoo._sync_individual(self._org(), dry_run=True) is None
        create.assert_not_called()
        lines.assert_not_called()


class TestSweepLapsedPersonalLines:
    """_sweep_lapsed_personal_lines removes unsourced lines from inactive contacts."""

    def _stale(self):
        return [
            {"id": 1, "x_partner_id": [8, "Jane"], "x_tier_id": [3, "Professional"]},
            {"id": 2, "x_partner_id": [9, "Joe"], "x_tier_id": [3, "Professional"]},
        ]

    def test_removes_stale_lines(self):
        """Every stale personal line is unlinked, excluding active contacts."""
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=self._stale()
        ) as search, patch.object(sync_odoo, "odoo_unlink") as unlink:
            sync_odoo._sweep_lapsed_personal_lines({20, 10}, dry_run=False)
        unlink.assert_called_once_with("x_plan_line", [1, 2])
        assert ["x_partner_id", "not in", [10, 20]] in search.call_args.args[1]

    def test_dry_run_no_unlink(self):
        """Dry-run reports but removes nothing."""
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=self._stale()
        ), patch.object(sync_odoo, "odoo_unlink") as unlink:
            sync_odoo._sweep_lapsed_personal_lines(set(), dry_run=True)
        unlink.assert_not_called()

    def test_nothing_stale(self):
        """No stale lines means no unlink call."""
        with patch.object(sync_odoo, "odoo_search_all", return_value=[]), patch.object(
            sync_odoo, "odoo_unlink"
        ) as unlink:
            sync_odoo._sweep_lapsed_personal_lines({1}, dry_run=False)
        unlink.assert_not_called()


class TestCancelOrg:
    """cancel_org sets sunlight status to Cancelled and notes the lines it held."""

    def test_writes_cancelled_status_and_names_lines(self):
        """A live cancel writes Cancelled and the note names the org's lines."""
        with patch.object(sync_odoo, "odoo_write") as write, patch.object(
            sync_odoo, "_line_names", return_value=["Essential"]
        ), patch.object(sync_odoo, "log_org_note") as note:
            sync_odoo.cancel_org(1, "Acme", dry_run=False)
        write.assert_called_once_with(
            "res.partner", [1], {"x_studio_sunlight_status": "Cancelled"}
        )
        assert "Essential" in note.call_args.args[1]

    def test_dry_run_no_write(self):
        """Dry-run performs no write."""
        with patch.object(sync_odoo, "odoo_write") as write, patch.object(
            sync_odoo, "_line_names", return_value=[]
        ), patch.object(sync_odoo, "log_org_note"):
            sync_odoo.cancel_org(1, "Acme", dry_run=True)
        write.assert_not_called()


class TestCollaborativeConfig:
    """CollaborativeConfig stores the resolved collaborative runtime data."""

    def test_stores_attributes(self):
        """The constructor stores slug, tag, members, Odoo id and line specs."""
        cfg = sync_odoo.CollaborativeConfig(
            "rural-news-network", 1, {"a", "b"}, 230, [_spec(source=230)]
        )
        assert cfg.slug == "rural-news-network"
        assert cfg.tag_id == 1
        assert cfg.member_slugs == {"a", "b"}
        assert cfg.odoo_id == 230
        assert cfg.line_specs == [_spec(source=230)]


class TestRemoveCollaborativeTag:
    """remove_collaborative_tag drops the tag and the lines sourced from it."""

    def test_removes_tag_and_sourced_lines(self):
        """The tag is unlinked, sourced lines on the org and its contacts go,
        and the note names only the org's own lines."""
        tagged = {"id": 1, "name": "Acme"}
        cfg = sync_odoo.CollaborativeConfig("rural-news-network", 3, set(), 230, [])
        sourced = [
            {"id": 5, "x_tier_id": [10, "Enterprise"], "x_partner_id": [1, "Acme"]},
            {"id": 6, "x_tier_id": [10, "Enterprise"], "x_partner_id": [2, "Jane"]},
        ]
        with patch.object(sync_odoo, "odoo_write") as write, patch.object(
            sync_odoo, "odoo_search_all", return_value=sourced
        ), patch.object(sync_odoo, "odoo_unlink") as unlink, patch.object(
            sync_odoo, "log_org_note"
        ) as note:
            sync_odoo.remove_collaborative_tag(tagged, cfg, dry_run=False)
        write.assert_called_once_with("res.partner", [1], {"category_id": [(3, 3)]})
        unlink.assert_called_once_with("x_plan_line", [5, 6])
        assert note.call_args.args[1].endswith("Enterprise")

    def test_no_odoo_partner_only_untags(self):
        """A collaborative missing from Odoo has no lines to remove."""
        tagged = {"id": 1, "name": "Acme"}
        cfg = sync_odoo.CollaborativeConfig("rural-news-network", 3, set(), None, [])
        with patch.object(sync_odoo, "odoo_write"), patch.object(
            sync_odoo, "odoo_search_all"
        ) as search, patch.object(sync_odoo, "log_org_note") as note:
            sync_odoo.remove_collaborative_tag(tagged, cfg, dry_run=False)
        search.assert_not_called()
        note.assert_not_called()

    def test_dry_run_no_write(self):
        """Dry-run performs no write."""
        tagged = {"id": 1, "name": "Acme"}
        cfg = sync_odoo.CollaborativeConfig("rural-news-network", 3, set(), 230, [])
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo.remove_collaborative_tag(tagged, cfg, dry_run=True)
        write.assert_not_called()


class TestCollaborativeRenewals:
    """_collaborative_renewals reads staff-set
    dates off the collaborative's own lines."""

    def test_maps_tier_to_date(self):
        """Each own line with a date maps its tier slug to that date."""
        lines = [
            {"x_tier_id": [ENTERPRISE_ID, "Enterprise"], "x_renews_on": "2026-11-30"},
            {"x_tier_id": [ESSENTIAL_ID, "Essential"], "x_renews_on": False},
        ]
        with patch.object(sync_odoo, "odoo_search_all", return_value=lines):
            assert sync_odoo._collaborative_renewals(230) == {
                "sunlight-enterprise": "2026-11-30"
            }


@pytest.mark.django_db
class TestBuildOrgVals:
    """_build_org_vals builds the res.partner vals with conditional fields."""

    def test_core_fields(self):
        """Core fields copy from the org, with no plan field."""
        org = OrganizationFactory(name="acme-vals-1")
        vals = sync_odoo._build_org_vals(org, None, None)
        assert vals["name"] == org.name
        assert vals["x_studio_slug"] == org.slug
        assert vals["is_company"] is True
        assert "x_studio_plan_1" not in vals

    def test_sunlight_status_only_when_set(self):
        """The sunlight-status key is present only when a status is given."""
        org = OrganizationFactory(name="acme-vals-2")
        assert "x_studio_sunlight_status" not in sync_odoo._build_org_vals(
            org, None, None
        )
        assert (
            sync_odoo._build_org_vals(org, "Confirmed", None)[
                "x_studio_sunlight_status"
            ]
            == "Confirmed"
        )

    def test_member_tags_use_link_command(self):
        """Member tags use the (4, id) link command."""
        org = OrganizationFactory(name="acme-vals-3")
        vals = sync_odoo._build_org_vals(org, None, [1, 3])
        assert vals["category_id"] == [(4, 1), (4, 3)]


@pytest.mark.django_db
class TestDiffAndUpdateOrg:
    """_diff_and_update_org writes only when the desired vals differ."""

    def _current_from_org(self, org, **overrides):
        """A fake Odoo row matching the org's vals, as a no-diff baseline."""
        base = {
            "id": 1,
            "name": org.name,
            "x_studio_slug": org.slug,
            "x_studio_muckrock_accounts_id": org.id,
            "x_studio_muckrock_accounts_uuid": str(org.uuid),
            "x_studio_muckrock_accounts": True,
            "city": org.city or "",
            "website": ", ".join(org.urls.values_list("url", flat=True)),
            "x_studio_verified_journalist": org.verified_journalist,
            "x_studio_sunlight_status": "Confirmed",
            "is_company": True,
            "company_type": "company",
            "x_studio_about": org.about or "",
            "category_id": [],
        }
        base.update(overrides)
        return base

    def _diff(self, org, current, status="Confirmed", tags=None, dry_run=False):
        vals = sync_odoo._build_org_vals(org, status, tags)
        with patch.object(
            sync_odoo, "odoo_search", return_value=[current]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._diff_and_update_org(org, 1, vals, status, tags, dry_run)
        return write

    def test_no_write_when_unchanged(self):
        """Desired vals identical to the current row produce no write."""
        org = OrganizationFactory(name="acme-diff-1")
        self._diff(org, self._current_from_org(org)).assert_not_called()

    def test_writes_when_field_changes(self):
        """A changed scalar field (city) triggers a single write."""
        org = OrganizationFactory(name="acme-diff-2", city="Cambridge")
        write = self._diff(org, self._current_from_org(org, city="Boston"))
        write.assert_called_once()

    def test_dry_run_never_writes(self):
        """Dry-run performs no write even when there is a diff."""
        org = OrganizationFactory(name="acme-diff-3", city="Cambridge")
        write = self._diff(
            org, self._current_from_org(org, city="Boston"), dry_run=True
        )
        write.assert_not_called()

    def test_false_empty_string_coercion_no_write(self):
        """Odoo's False for an empty char field equals a desired ''."""
        org = OrganizationFactory(name="acme-diff-4", city="")
        write = self._diff(org, self._current_from_org(org, city=False))
        write.assert_not_called()

    def test_missing_member_tag_triggers_write(self):
        """A member tag absent from the current row triggers a write."""
        org = OrganizationFactory(name="acme-diff-5")
        write = self._diff(org, self._current_from_org(org, category_id=[]), tags=[1])
        write.assert_called_once()


@pytest.mark.django_db
class TestBuildOrgQueryset:
    """_build_org_queryset includes every subscribed group org."""

    def test_includes_any_subscribed_group_org(self):
        """Group orgs on wix and non-wix plans are both included."""
        wix_plan = PlanFactory(name="Sunlight X", wix=True)
        pro_plan = PlanFactory(name="Organization X", wix=False)
        wix_org = OrganizationFactory(name="wix-org", plans=[wix_plan])
        pro_org = OrganizationFactory(name="pro-org", plans=[pro_plan])
        slugs = set(sync_odoo._build_org_queryset({}).values_list("slug", flat=True))
        assert wix_org.slug in slugs
        assert pro_org.slug in slugs

    def test_excludes_unsubscribed_org(self):
        """A group org with no subscription line is not synced."""
        OrganizationFactory(name="bare-org", slug="bare-org")
        slugs = set(sync_odoo._build_org_queryset({}).values_list("slug", flat=True))
        assert "bare-org" not in slugs

    def test_excludes_individual_orgs(self):
        """An individual org is left to the individual pass."""
        plan = PlanFactory(name="Sunlight Y", wix=True)
        OrganizationFactory(name="indiv-org", plans=[plan], individual=True)
        slugs = set(sync_odoo._build_org_queryset({}).values_list("slug", flat=True))
        assert "indiv-org" not in slugs

    def test_skip_slugs_removed(self):
        """An org whose slug is in SKIP_SLUGS is excluded."""
        plan = PlanFactory(name="Sunlight Z", wix=True)
        skip = next(iter(sync_odoo.SKIP_SLUGS))
        OrganizationFactory(name=skip, slug=skip, plans=[plan])
        slugs = set(sync_odoo._build_org_queryset({}).values_list("slug", flat=True))
        assert skip not in slugs

    def test_collaborative_members_folded_in(self):
        """A collaborative member with no subscription of its own is still included."""
        OrganizationFactory(name="collab-member", slug="collab-member")
        cfg = sync_odoo.CollaborativeConfig(
            "rural-news-network", 1, {"collab-member"}, 230, []
        )
        qs = sync_odoo._build_org_queryset({"rural-news-network": cfg})
        assert "collab-member" in set(qs.values_list("slug", flat=True))


@pytest.mark.django_db
class TestBuildIndividualQueryset:
    """_build_individual_queryset selects subscribed individual orgs only."""

    def test_includes_subscribed_individual(self):
        """An individual org with a subscription line is included."""
        plan = PlanFactory(name="Professional X")
        OrganizationFactory(
            name="pro-user", slug="pro-user", plans=[plan], individual=True
        )
        slugs = set(
            sync_odoo._build_individual_queryset().values_list("slug", flat=True)
        )
        assert "pro-user" in slugs

    def test_excludes_group_org(self):
        """A subscribed group org is left to the org pass."""
        plan = PlanFactory(name="Organization Y")
        OrganizationFactory(name="group-org", slug="group-org", plans=[plan])
        slugs = set(
            sync_odoo._build_individual_queryset().values_list("slug", flat=True)
        )
        assert "group-org" not in slugs


@pytest.mark.django_db
class TestLoadCollaborativeData:
    """_load_collaborative_data resolves configs from the DB, settings and Odoo."""

    @override_settings(COLLABORATIVE_TAGS={})
    def test_unconfigured_collaborative_skipped(self):
        """A collective-enabled org with no configured tag is skipped."""
        plan = PlanFactory(name="Collab Enterprise A", wix=True)
        OrganizationFactory(
            name="collab-a", slug="collab-a", plans=[plan], collective_enabled=True
        )
        assert not sync_odoo._load_collaborative_data()

    @override_settings(COLLABORATIVE_TAGS={"collab-b": 7})
    def test_resolves_configured_collaborative(self):
        """A configured collaborative carries its members and sourced, unrated lines."""
        plan = PlanFactory(
            name="Collab Enterprise B", slug="collab-enterprise-b", wix=True
        )
        member = OrganizationFactory(name="member-b", slug="member-b")
        collab = OrganizationFactory(
            name="collab-b", slug="collab-b", plans=[plan], collective_enabled=True
        )
        collab.members.add(member)
        with patch.object(
            sync_odoo, "odoo_search", return_value=[{"id": 230}]
        ), patch.object(sync_odoo, "odoo_search_all", return_value=[]):
            data = sync_odoo._load_collaborative_data()
        cfg = data["collab-b"]
        assert cfg.tag_id == 7
        assert cfg.odoo_id == 230
        assert "member-b" in cfg.member_slugs
        assert len(cfg.line_specs) == 1
        assert cfg.line_specs[0]["x_source_id"] == 230
        assert cfg.line_specs[0]["x_rate"] is False

    @override_settings(COLLABORATIVE_TAGS={"collab-d": 9})
    def test_inherited_renewal_falls_back_to_odoo(self):
        """With no Accounts date, inherited lines take the collaborative's Odoo date."""
        plan = PlanFactory(
            name="Collab Enterprise D", slug="collab-enterprise-d", wix=True
        )
        OrganizationFactory(
            name="collab-d", slug="collab-d", plans=[plan], collective_enabled=True
        )
        sync_odoo._TIER_SLUG_BY_ID[50] = "collab-enterprise-d"
        own_lines = [{"x_tier_id": [50, "Enterprise D"], "x_renews_on": "2026-11-30"}]
        with patch.object(
            sync_odoo, "odoo_search", return_value=[{"id": 231}]
        ), patch.object(sync_odoo, "odoo_search_all", return_value=own_lines):
            data = sync_odoo._load_collaborative_data()
        assert data["collab-d"].line_specs[0]["x_renews_on"] == "2026-11-30"

    @override_settings(COLLABORATIVE_TAGS={"collab-e": 10})
    def test_collaborative_missing_from_odoo_has_no_lines(self):
        """A collaborative with no Odoo partner is loaded without inherited lines."""
        plan = PlanFactory(name="Collab Enterprise E", wix=True)
        OrganizationFactory(
            name="collab-e", slug="collab-e", plans=[plan], collective_enabled=True
        )
        with patch.object(sync_odoo, "odoo_search", return_value=[]):
            data = sync_odoo._load_collaborative_data()
        assert data["collab-e"].odoo_id is None
        assert data["collab-e"].line_specs == []

    @override_settings(COLLABORATIVE_TAGS={"collab-c": 8})
    def test_non_collective_org_ignored(self):
        """An org in the tag map but not collective_enabled is not loaded."""
        OrganizationFactory(name="collab-c", slug="collab-c", collective_enabled=False)
        assert not sync_odoo._load_collaborative_data()


@pytest.mark.django_db
class TestHandle:
    """handle emails a FAILED report on error and OK on a clean run."""

    @override_settings(ODOO_SYNC_ENABLED=True)
    def test_failed_request_sends_failed_email_and_reraises(self):
        """An Odoo failure re-raises and emails a FAILED report with a log."""
        with patch.object(
            sync_odoo,
            "_odoo_request",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            with pytest.raises(requests.exceptions.ConnectionError):
                call_command("sync_odoo")
        assert len(mail.outbox) == 1
        assert "FAILED" in mail.outbox[0].subject
        assert mail.outbox[0].attachments

    @override_settings(ODOO_SYNC_ENABLED=True)
    def test_clean_run_sends_ok_email(self):
        """A clean run emails a single OK report."""
        with patch.object(sync_odoo, "_odoo_request", return_value=[]):
            call_command("sync_odoo")
        assert len(mail.outbox) == 1
        assert "OK" in mail.outbox[0].subject
