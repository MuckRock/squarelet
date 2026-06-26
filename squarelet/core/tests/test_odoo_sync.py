# Django
from django.core import mail
from django.core.management import call_command

# Standard Library
from datetime import date
from unittest.mock import Mock, patch

# Third Party
import pytest
import requests

# Squarelet
from squarelet.core.management.commands import sync_odoo
from squarelet.organizations.tests.factories import OrganizationFactory, PlanFactory

# pylint:disable=protected-access


@pytest.fixture(autouse=True)
def clear_plan_cache():
    """_PLAN_ID_CACHE is module-global; reset it around every test."""
    sync_odoo._PLAN_ID_CACHE.clear()
    yield
    sync_odoo._PLAN_ID_CACHE.clear()


class TestOdooRequest:
    """_odoo_request returns parsed JSON on success and raises on failure."""

    def test_returns_json_on_success(self):
        """A successful POST returns the parsed JSON body."""
        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = [{"id": 42}]
        with patch.object(sync_odoo._session, "post", return_value=resp) as post:
            result = sync_odoo._odoo_request("x_plan/search_read", {"domain": []})
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
                sync_odoo._odoo_request("x_plan/search_read", {"domain": []})

    def test_raises_on_bad_status(self):
        """A non-2xx response (raise_for_status) propagates as HTTPError."""
        resp = Mock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("400")
        with patch.object(sync_odoo._session, "post", return_value=resp):
            with pytest.raises(requests.exceptions.HTTPError):
                sync_odoo._odoo_request("x_plan/create", {"vals_list": [{}]})

    def test_does_not_return_none_on_failure(self):
        """Regression guard: failure must not masquerade as 'no result'."""
        with patch.object(
            sync_odoo._session,
            "post",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            with pytest.raises(requests.exceptions.RequestException):
                sync_odoo._odoo_request("x_plan/search_read", {"domain": []})


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


class TestOdooCreate:
    """odoo_create wraps vals in a vals_list payload."""

    def test_wraps_vals_in_vals_list(self):
        """A single vals dict is wrapped in the vals_list the API expects."""
        with patch.object(sync_odoo, "_odoo_request", return_value=[7]) as req:
            result = sync_odoo.odoo_create("x_plan", {"x_name": "Pro"})
        assert result == [7]
        req.assert_called_once_with("x_plan/create", {"vals_list": [{"x_name": "Pro"}]})


class TestOdooWrite:
    """odoo_write passes ids and vals through unchanged."""

    def test_passes_ids_and_vals(self):
        """ids and vals are forwarded to the write endpoint verbatim."""
        with patch.object(sync_odoo, "_odoo_request", return_value=True) as req:
            sync_odoo.odoo_write("res.partner", [3], {"city": "NYC"})
        req.assert_called_once_with(
            "res.partner/write", {"ids": [3], "vals": {"city": "NYC"}}
        )


class TestResolvePlanId:
    """_resolve_plan_id looks up by name and caches the result."""

    def test_returns_cached_value_without_search(self):
        """A cached name returns its id without hitting odoo_search."""
        sync_odoo._PLAN_ID_CACHE["Pro"] = 99
        with patch.object(sync_odoo, "odoo_search") as search:
            assert sync_odoo._resolve_plan_id("Pro") == 99
        search.assert_not_called()

    def test_resolves_and_caches_existing_plan(self):
        """A found plan returns its id and stores it in the cache."""
        with patch.object(sync_odoo, "odoo_search", return_value=[{"id": 5}]):
            assert sync_odoo._resolve_plan_id("Pro") == 5
        assert sync_odoo._PLAN_ID_CACHE["Pro"] == 5

    def test_missing_caches_none(self):
        """A plan with no Odoo match returns None and caches None."""
        with patch.object(sync_odoo, "odoo_search", return_value=[]):
            assert sync_odoo._resolve_plan_id("Ghost") is None
        assert sync_odoo._PLAN_ID_CACHE["Ghost"] is None


class TestBuildPlanVals:
    """_build_plan_vals maps a Squarelet Plan to the mirrored x_plan fields."""

    def test_maps_all_mirrored_fields(self):
        """All five mirrored plan fields map to their x_ counterparts."""
        plan = Mock()
        plan.name = "Scoutpost Team"
        plan.slug = "scoutpost-team"
        plan.base_price = 50.0
        plan.price_per_user = 10.0
        plan.annual = False
        assert sync_odoo._build_plan_vals(plan) == {
            "x_name": "Scoutpost Team",
            "x_studio_slug": "scoutpost-team",
            "x_studio_base_price": 50.0,
            "x_studio_price_per_user": 10.0,
            "x_studio_annual": False,
        }


class TestComputeOrgPlansAndStatus:
    """_compute_org_plans_and_status resolves plans and sets sunlight status."""

    def test_confirmed_when_any_wix_plan(self):
        """An own wix plan sets status Confirmed and resolves all plan ids."""
        org = Mock()
        org.plans.values_list.return_value = [("Pro", True), ("Free", False)]
        with patch.object(sync_odoo, "_resolve_plan_id", side_effect=[10, 20]):
            ids, status = sync_odoo._compute_org_plans_and_status(org, None)
        assert ids == [10, 20]
        assert status == "Confirmed"

    def test_no_status_without_wix_plan(self):
        """No own wix plan leaves the sunlight status unset."""
        org = Mock()
        org.plans.values_list.return_value = [("Free", False)]
        with patch.object(sync_odoo, "_resolve_plan_id", return_value=20):
            _, status = sync_odoo._compute_org_plans_and_status(org, None)
        assert status is None

    def test_inherited_plans_merged_and_deduped(self):
        """Inherited ids are merged with own ids and duplicates removed."""
        org = Mock()
        org.plans.values_list.return_value = [("Pro", True)]
        with patch.object(sync_odoo, "_resolve_plan_id", return_value=10):
            ids, _ = sync_odoo._compute_org_plans_and_status(org, [10, 30])
        assert ids == [10, 30]

    def test_inherited_plans_do_not_set_sunlight_status(self):
        """Sunlight status is computed from the org's OWN plans only —
        inherited (collaborative/enterprise) plans must not confirm it."""
        org = Mock()
        # own plans: none of them wix
        org.plans.values_list.return_value = [("Free", False)]
        with patch.object(sync_odoo, "_resolve_plan_id", return_value=20):
            ids, status = sync_odoo._compute_org_plans_and_status(
                org, inherited_plan_ids=[101, 102]
            )
        # inherited ids ARE included in the plan list...
        assert 101 in ids and 102 in ids
        # ...but they do NOT flip sunlight status on
        assert status is None

    def test_own_wix_plan_confirms_even_with_inherited(self):
        """An own wix plan sets Confirmed; inherited plans are additive, not
        the trigger."""
        org = Mock()
        org.plans.values_list.return_value = [("Sunlight Basic", True)]
        with patch.object(sync_odoo, "_resolve_plan_id", return_value=10):
            ids, status = sync_odoo._compute_org_plans_and_status(
                org, inherited_plan_ids=[101]
            )
        assert status == "Confirmed"
        assert 10 in ids and 101 in ids


class TestMemberDesiredPlans:
    """_member_desired_plans unions org and personal plans, dropping unresolved."""

    def test_unions_org_and_personal_plans(self):
        """Org plans and the user's personal plans are unioned."""
        user = Mock()
        user.individual_organization.plans.values_list.return_value = ["Personal"]
        with patch.object(sync_odoo, "_resolve_plan_id", return_value=30):
            assert sync_odoo._member_desired_plans(user, [10, 20]) == [10, 20, 30]

    def test_drops_unresolved_personal_plan(self):
        """An unresolved personal plan is dropped; org plans are kept.
        This shouldn't ever happen as we ensure all plans at the beginning,
        but it is important we still have a test case
        """
        user = Mock()
        user.individual_organization.plans.values_list.return_value = ["Broken"]
        with patch.object(sync_odoo, "_resolve_plan_id", return_value=None):
            assert sync_odoo._member_desired_plans(user, [10]) == [10]


class TestFindMember:
    """_find_member matches by primary email, then secondary."""

    def test_primary_match(self):
        """A primary-email hit returns its id and matched_via_secondary=False."""
        with patch.object(sync_odoo, "odoo_search", return_value=[{"id": 3}]):
            assert sync_odoo._find_member("a@b.com") == (3, False)

    def test_secondary_match(self):
        """No primary hit but a secondary hit returns id and True."""
        with patch.object(sync_odoo, "odoo_search", side_effect=[[], [{"id": 8}]]):
            assert sync_odoo._find_member("a@b.com") == (8, True)

    def test_no_match(self):
        """Neither primary nor secondary match returns (None, False)."""
        with patch.object(sync_odoo, "odoo_search", side_effect=[[], []]):
            assert sync_odoo._find_member("a@b.com") == (None, False)


class TestMemberVals:
    """_member_vals builds contact vals, omitting email on secondary match."""

    def _user(self):
        user = Mock()
        user.name = "Jane"
        user.email = "jane@b.com"
        user.id = 5
        user.uuid = "u-5"
        return user

    def test_includes_email_by_default(self):
        """A primary/new match includes email and the parent link."""
        vals = sync_odoo._member_vals(self._user(), 1, matched_via_secondary=False)
        assert vals["email"] == "jane@b.com"
        assert vals["parent_id"] == 1

    def test_omits_email_when_matched_via_secondary(self):
        """A secondary-email match omits email to avoid clobbering the primary
        on Odoo."""
        vals = sync_odoo._member_vals(self._user(), 1, matched_via_secondary=True)
        assert "email" not in vals


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
        """An Odoo contact that is still on Accounts
        but absent from the roster is departed."""
        member = {"email": "a@b.com", "x_studio_muckrock_accounts": True}
        assert sync_odoo._is_departed(member, {"other@b.com"}) is True


class TestUnlinkDepartedMember:
    """_unlink_departed_member clears parent and strips inherited plans."""

    def test_strips_inherited_plans_only(self):
        """Only org-inherited plans are removed; personal plans are kept."""
        member = {"id": 8, "email": "a@b.com", "x_studio_plan_1": [10, 20, 30]}
        org = Mock()
        org.name = "Acme"
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._unlink_departed_member(member, org, {20, 30}, dry_run=False)
        written = write.call_args.args[2]
        assert written["parent_id"] is False
        assert written["x_studio_plan_1"] == [(6, 0, [10])]

    def test_dry_run_no_write(self):
        """Dry-run performs no write."""
        member = {"id": 8, "email": "a@b.com", "x_studio_plan_1": [10]}
        org = Mock()
        org.name = "Acme"
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._unlink_departed_member(member, org, {10}, dry_run=True)
        write.assert_not_called()

    def test_no_inherited_plans_only_clears_parent(self):
        """Departed member holding no org-inherited plans: parent is cleared
        but x_studio_plan_1 is left untouched (personal plans preserved).
        Edge case."""
        member = {"id": 8, "email": "a@b.com", "x_studio_plan_1": [10, 11]}
        org = Mock()
        org.name = "Acme"
        with patch.object(sync_odoo, "odoo_write") as write:
            # org_plans = {99} -> no overlap with member's [10, 11]
            sync_odoo._unlink_departed_member(member, org, {99}, dry_run=False)
        written = write.call_args.args[2]
        assert written["parent_id"] is False
        assert "x_studio_plan_1" not in written


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
        org.users.values_list.return_value = ["stay@b.com"]
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
            sync_odoo.remove_departed_members(self._org(), 1, [10], remove=False)
        flag.assert_called_once()
        unlink.assert_not_called()

    def test_unlinks_when_removing(self):
        """With remove=True a departed member is unlinked."""
        members = [{"id": 8, "email": "gone@b.com"}]
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=members
        ), patch.object(sync_odoo, "_is_departed", return_value=True), patch.object(
            sync_odoo, "_unlink_departed_member"
        ) as unlink:
            sync_odoo.remove_departed_members(self._org(), 1, [10], remove=True)
        unlink.assert_called_once()

    def test_skips_non_departed(self):
        """A member still in the org triggers neither flag nor unlink."""
        members = [{"id": 8, "email": "stay@b.com"}]
        with patch.object(
            sync_odoo, "odoo_search_all", return_value=members
        ), patch.object(sync_odoo, "_is_departed", return_value=False), patch.object(
            sync_odoo, "_flag_departed_member"
        ) as flag:
            sync_odoo.remove_departed_members(self._org(), 1, [10], remove=False)
        flag.assert_not_called()


class TestCancelOrg:
    """cancel_org sets sunlight status to Cancelled unless dry-run."""

    def test_writes_cancelled_status(self):
        """A live cancel writes the Cancelled sunlight status."""
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo.cancel_org(1, "Acme", dry_run=False)
        write.assert_called_once_with(
            "res.partner", [1], {"x_studio_sunlight_status": "Cancelled"}
        )

    def test_dry_run_no_write(self):
        """Dry-run performs no write."""
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo.cancel_org(1, "Acme", dry_run=True)
        write.assert_not_called()


class TestRemoveCollaborativeTag:
    """remove_collaborative_tag drops the tag and its inherited plans only."""

    def test_removes_tag_and_inherited_plans(self):
        """The tag is unlinked and only this collaborative's plans are dropped."""
        tagged = {"id": 1, "name": "Acme", "x_studio_plan_1": [10, 20]}
        cfg = sync_odoo.CollaborativeConfig(3, "RNN", [20], set())
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo.remove_collaborative_tag(tagged, cfg, dry_run=False)
        written = write.call_args.args[2]
        assert written["category_id"] == [(3, 3)]
        assert written["x_studio_plan_1"] == [(6, 0, [10])]

    def test_dry_run_no_write(self):
        """Dry-run performs no write."""
        tagged = {"id": 1, "name": "Acme", "x_studio_plan_1": [10]}
        cfg = sync_odoo.CollaborativeConfig(3, "RNN", [10], set())
        with patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo.remove_collaborative_tag(tagged, cfg, dry_run=True)
        write.assert_not_called()


class TestCollaborativeConfig:
    """CollaborativeConfig stores the resolved collaborative runtime data."""

    def test_stores_attributes(self):
        """The constructor stores tag_id, label, plan_ids and member_slugs."""
        cfg = sync_odoo.CollaborativeConfig(1, "RNN", [10], {"a", "b"})
        assert (cfg.tag_id, cfg.label, cfg.plan_ids) == (1, "RNN", [10])
        assert cfg.member_slugs == {"a", "b"}


class TestUpdateMember:
    """_update_member diffs an existing member and guards parent reassignment."""

    def _current(self, **overrides):
        base = {
            "id": 8,
            "name": "Jane",
            "email": "jane@b.com",
            "parent_id": [1, "Acme"],  # Odoo m2o comes back as [id, label]
            "is_company": False,
            "company_type": "person",
            "x_studio_muckrock_accounts": True,
            "x_studio_muckrock_accounts_id": 5,
            "x_studio_muckrock_accounts_uuid": "u-5",
            "x_studio_plan_1": [10],
        }
        base.update(overrides)
        return base

    def _matching_vals(self):
        # vals that exactly match _current() -> should produce no write
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
            sync_odoo._update_member(
                user, "Acme", 8, self._matching_vals(), [10], dry_run=False
            )
        write.assert_not_called()

    def test_plan_change_triggers_write_with_replace_command(self):
        """A changed plan set writes the (6, 0, ids) replace command."""
        user = Mock(email="jane@b.com")
        with patch.object(
            sync_odoo, "odoo_search", return_value=[self._current()]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._update_member(
                user, "Acme", 8, self._matching_vals(), [10, 20], dry_run=False
            )
        written = write.call_args.args[2]
        assert written["x_studio_plan_1"] == [(6, 0, [10, 20])]

    def test_does_not_reassign_existing_parent(self):
        """Member already has a parent in Odoo -> parent_id is dropped from
        the write so the existing link is never overwritten."""
        user = Mock(email="jane@b.com")
        vals = self._matching_vals()
        vals["parent_id"] = 999  # a different parent than current (1)
        with patch.object(
            sync_odoo, "odoo_search", return_value=[self._current()]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._update_member(user, "Acme", 8, vals, [10], dry_run=False)
        # parent differs and plans match -> nothing left to write
        write.assert_not_called()

    def test_dry_run_no_write(self):
        """Dry-run performs no write even when there is a diff."""
        user = Mock(email="jane@b.com")
        with patch.object(
            sync_odoo, "odoo_search", return_value=[self._current()]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._update_member(
                user, "Acme", 8, self._matching_vals(), [10, 20], dry_run=True
            )
        write.assert_not_called()


@pytest.mark.django_db
class TestBuildOrgVals:
    """_build_org_vals builds the res.partner vals with conditional fields."""

    def test_core_fields_and_plan_command(self):
        """Core fields copy from the org and plans use the (6, 0, ids) command."""
        org = OrganizationFactory(name="acme-vals-1")
        vals = sync_odoo._build_org_vals(org, [5], None, None)
        assert vals["name"] == org.name
        assert vals["x_studio_slug"] == org.slug
        assert vals["x_studio_plan_1"] == [(6, 0, [5])]
        assert vals["is_company"] is True

    def test_sunlight_status_only_when_set(self):
        """The sunlight-status key is present only when a status is given."""
        org = OrganizationFactory(name="acme-vals-2")
        assert "x_studio_sunlight_status" not in sync_odoo._build_org_vals(
            org, [], None, None
        )
        assert (
            sync_odoo._build_org_vals(org, [], "Confirmed", None)[
                "x_studio_sunlight_status"
            ]
            == "Confirmed"
        )

    def test_member_tags_use_link_command(self):
        """Member tags use the (4, id) link command."""
        org = OrganizationFactory(name="acme-vals-3")
        vals = sync_odoo._build_org_vals(org, [], None, [1, 3])
        assert vals["category_id"] == [(4, 1), (4, 3)]


@pytest.mark.django_db
class TestDiffAndUpdateOrg:
    """_diff_and_update_org writes only when the desired vals differ.

    Uses a real Organization (via factory) so _build_org_vals reads genuine
    model attributes; the Odoo side is mocked.
    """

    def _current_from_org(self, org, **overrides):
        """A fake Odoo 'current' row that matches the given org's vals,
        so the default is a no-diff baseline each test can perturb."""
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
            "x_studio_plan_1": [5],
            "is_company": True,
            "company_type": "company",
            "x_studio_about": org.about or "",
            "category_id": [],
        }
        base.update(overrides)
        return base

    def test_no_write_when_unchanged(self):
        """Desired vals identical to the current row produce no write."""
        org = OrganizationFactory(name="acme-diff-1")
        vals = sync_odoo._build_org_vals(org, [5], "Confirmed", None)
        current = self._current_from_org(org)
        with patch.object(
            sync_odoo, "odoo_search", return_value=[current]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._diff_and_update_org(
                org, 1, vals, [5], "Confirmed", None, dry_run=False
            )
        write.assert_not_called()

    def test_writes_when_field_changes(self):
        """A changed scalar field (city) triggers a single write."""
        org = OrganizationFactory(name="acme-diff-2", city="Cambridge")
        vals = sync_odoo._build_org_vals(org, [5], "Confirmed", None)
        # current row has a different city -> a real diff
        current = self._current_from_org(org, city="Boston")
        with patch.object(
            sync_odoo, "odoo_search", return_value=[current]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._diff_and_update_org(
                org, 1, vals, [5], "Confirmed", None, dry_run=False
            )
        write.assert_called_once()

    def test_writes_when_plans_change(self):
        """A changed plan set triggers a write."""
        org = OrganizationFactory(name="acme-diff-3")
        vals = sync_odoo._build_org_vals(org, [5, 6], "Confirmed", None)
        current = self._current_from_org(org, x_studio_plan_1=[5])
        with patch.object(
            sync_odoo, "odoo_search", return_value=[current]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._diff_and_update_org(
                org, 1, vals, [5, 6], "Confirmed", None, dry_run=False
            )
        write.assert_called_once()

    def test_dry_run_never_writes(self):
        """Dry-run performs no write even when there is a diff."""
        org = OrganizationFactory(name="acme-diff-4", city="Cambridge")
        vals = sync_odoo._build_org_vals(org, [5], "Confirmed", None)
        current = self._current_from_org(org, city="Boston")
        with patch.object(
            sync_odoo, "odoo_search", return_value=[current]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._diff_and_update_org(
                org, 1, vals, [5], "Confirmed", None, dry_run=True
            )
        write.assert_not_called()

    def test_false_empty_string_coercion_no_write(self):
        """Odoo returns False for an empty char field; a desired '' must be
        treated as equal, not a spurious diff that triggers a write."""
        org = OrganizationFactory(name="acme-diff-5", city="")
        vals = sync_odoo._build_org_vals(org, [5], "Confirmed", None)
        # Odoo stores the empty city as False rather than ""
        current = self._current_from_org(org, city=False)
        with patch.object(
            sync_odoo, "odoo_search", return_value=[current]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._diff_and_update_org(
                org, 1, vals, [5], "Confirmed", None, dry_run=False
            )
        write.assert_not_called()

    def test_missing_member_tag_triggers_write(self):
        """A member tag absent from the current row triggers a write."""
        org = OrganizationFactory(name="acme-diff-6")
        vals = sync_odoo._build_org_vals(org, [5], "Confirmed", [1])
        # org has no tags in Odoo yet -> the desired tag is missing
        current = self._current_from_org(org, category_id=[])
        with patch.object(
            sync_odoo, "odoo_search", return_value=[current]
        ), patch.object(sync_odoo, "odoo_write") as write:
            sync_odoo._diff_and_update_org(
                org, 1, vals, [5], "Confirmed", [1], dry_run=False
            )
        write.assert_called_once()


@pytest.mark.django_db
class TestEnsureAllPlans:
    """_ensure_all_plans creates missing x_plan rows with full pricing data."""

    def test_creates_missing_plans_with_full_data(self):
        """A plan absent in Odoo is created with all mirrored pricing fields."""
        PlanFactory(
            name="Scoutpost Pro",
            slug="scoutpost-pro",
            base_price=10,
            price_per_user=0,
            annual=False,
            wix=True,
        )
        with patch.object(sync_odoo, "odoo_search", return_value=[]), patch.object(
            sync_odoo, "odoo_create", return_value=[200]
        ) as create:
            sync_odoo._ensure_all_plans(dry_run=False)
        payloads = [c.args[1] for c in create.call_args_list]
        ours = next(p for p in payloads if p["x_name"] == "Scoutpost Pro")
        assert ours == {
            "x_name": "Scoutpost Pro",
            "x_studio_slug": "scoutpost-pro",
            "x_studio_base_price": 10,
            "x_studio_price_per_user": 0,
            "x_studio_annual": False,
        }
        assert sync_odoo._PLAN_ID_CACHE["Scoutpost Pro"] == 200

    def test_existing_plan_is_not_recreated(self):
        """A plan already present in Odoo is cached, not recreated."""
        PlanFactory(name="Already There", wix=True)
        with patch.object(
            sync_odoo, "odoo_search", return_value=[{"id": 77}]
        ), patch.object(sync_odoo, "odoo_create") as create:
            sync_odoo._ensure_all_plans(dry_run=False)
        create.assert_not_called()
        assert sync_odoo._PLAN_ID_CACHE["Already There"] == 77

    def test_dry_run_creates_nothing(self):
        """Dry-run creates no plans and caches None for the missing one."""
        PlanFactory(name="Would Create", wix=True)
        with patch.object(sync_odoo, "odoo_search", return_value=[]), patch.object(
            sync_odoo, "odoo_create"
        ) as create:
            sync_odoo._ensure_all_plans(dry_run=True)
        create.assert_not_called()
        assert sync_odoo._PLAN_ID_CACHE["Would Create"] is None


@pytest.mark.django_db
class TestBuildOrgQueryset:
    """_build_org_queryset includes wix orgs and excludes the rest."""

    def test_includes_wix_org_excludes_non_wix(self):
        """A wix-plan org is selected; a non-wix org is not."""
        wix_plan = PlanFactory(name="Sunlight X", wix=True)
        free_plan = PlanFactory(name="Free X", wix=False)
        included = OrganizationFactory(name="included-org", plans=[wix_plan])
        OrganizationFactory(name="excluded-org", plans=[free_plan])
        qs = sync_odoo._build_org_queryset({})
        slugs = set(qs.values_list("slug", flat=True))
        assert included.slug in slugs
        assert "excluded-org" not in slugs

    def test_excludes_individual_orgs(self):
        """An individual org is excluded even with a wix plan."""
        wix_plan = PlanFactory(name="Sunlight Y", wix=True)
        OrganizationFactory(name="indiv-org", plans=[wix_plan], individual=True)
        qs = sync_odoo._build_org_queryset({})
        assert "indiv-org" not in set(qs.values_list("slug", flat=True))

    def test_skip_slugs_removed(self):
        """An org whose slug is in SKIP_SLUGS is excluded."""
        wix_plan = PlanFactory(name="Sunlight Z", wix=True)
        skip = next(iter(sync_odoo.SKIP_SLUGS))
        OrganizationFactory(name=skip, slug=skip, plans=[wix_plan])
        qs = sync_odoo._build_org_queryset({})
        assert skip not in set(qs.values_list("slug", flat=True))

    def test_collaborative_members_folded_in(self):
        """A collaborative member with no own wix plan is still included."""
        OrganizationFactory(name="collab-member", slug="collab-member")
        cfg = sync_odoo.CollaborativeConfig(
            tag_id=1, label="RNN", plan_ids=[], member_slugs={"collab-member"}
        )
        qs = sync_odoo._build_org_queryset({"rural-news-network": cfg})
        assert "collab-member" in set(qs.values_list("slug", flat=True))


@pytest.mark.django_db
class TestLoadCollaborativeData:
    """_load_collaborative_data resolves configs, handling missing orgs."""

    def test_missing_collaborative_org_yields_empty_config(self):
        """A COLLABORATIVES slug with no matching org yields an empty config."""
        data = sync_odoo._load_collaborative_data()
        for slug in sync_odoo.COLLABORATIVES:
            assert data[slug].plan_ids == []
            assert data[slug].member_slugs == set()

    def test_resolves_members_and_plans_for_present_collab(self):
        """A present collaborative resolves its plan ids and member slugs."""
        slug = next(iter(sync_odoo.COLLABORATIVES))
        tag_id, label = sync_odoo.COLLABORATIVES[slug]
        wix_plan = PlanFactory(name="Collab Enterprise", wix=True)
        member = OrganizationFactory(name="a-member", slug="a-member")
        collab = OrganizationFactory(name=slug, slug=slug, plans=[wix_plan])
        collab.members.add(member)
        with patch.object(sync_odoo, "_resolve_plan_id", return_value=101):
            data = sync_odoo._load_collaborative_data()
        cfg = data[slug]
        assert cfg.tag_id == tag_id
        assert cfg.label == label
        assert 101 in cfg.plan_ids
        assert "a-member" in cfg.member_slugs


@pytest.mark.django_db
class TestHandle:
    """handle emails a FAILED report on error and OK on a clean run."""

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

    def test_clean_run_sends_ok_email(self):
        """A clean run emails a single OK report."""
        with patch.object(sync_odoo, "_odoo_request", return_value=[]):
            call_command("sync_odoo")
        assert len(mail.outbox) == 1
        assert "OK" in mail.outbox[0].subject
