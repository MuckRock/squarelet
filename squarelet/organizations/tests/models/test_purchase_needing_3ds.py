"""A purchase whose card needs 3D Secure keeps its lines while the customer
authenticates: Stripe charges once they do, and only finds a plan to activate
if Squarelet still has the subscription."""

# Standard Library
from unittest.mock import Mock

# Third Party
import pytest

# Squarelet
from squarelet.organizations import tasks
from squarelet.organizations.models import Subscription
from squarelet.organizations.payments.base import PaymentActionRequired
from squarelet.organizations.tests.factories import for_sale


@pytest.fixture(name="stripe_needs_3ds")
def stripe_needs_3ds_fixture(mocker):
    """Stripe accepts the purchase but leaves its first charge unauthenticated."""
    mocker.patch(
        "squarelet.organizations.models.Organization.customer",
        return_value=mocker.MagicMock(),
    )
    org_provider = mocker.patch(
        "squarelet.organizations.models.organization.get_payment_provider"
    ).return_value
    org_subscriptions = org_provider.get_subscription_service.return_value
    org_subscriptions.get_current_period_end.return_value = 1_800_000_000
    provider = mocker.patch(
        "squarelet.organizations.models.payment.get_payment_provider"
    ).return_value
    stripe_sub = Mock(id="sub_3ds", status="incomplete", latest_invoice="in_3ds")
    subscriptions = provider.get_subscription_service.return_value
    subscriptions.create.return_value = stripe_sub
    subscriptions.retrieve.return_value = stripe_sub
    subscriptions.modify.return_value = stripe_sub
    invoice = Mock(status="open", id="in_3ds")
    invoice.confirmation_secret.client_secret = "pi_3ds_secret_456"
    provider.get_invoice_service.return_value.retrieve.return_value = invoice
    return mocker.patch(
        "squarelet.organizations.models.Invoice.create_or_update_from_stripe",
        return_value=(None, True),
    )


@pytest.mark.django_db()
class TestPurchaseNeedingThreeDS:
    def test_a_new_subscription_is_kept_for_the_webhooks(
        self, organization_factory, user_factory, plan_factory, stripe_needs_3ds
    ):
        user = user_factory()
        organization = organization_factory(admins=[user])
        plan = for_sale(plan_factory(annual=False, base_price=40, minimum_users=1))

        with pytest.raises(PaymentActionRequired):
            organization.add_subscription(plan, None, user, payment_method="card")

        item = organization.subscription_items.get(plan=plan)
        assert item.subscription.subscription_id == "sub_3ds"
        # `invoice.paid` only acts on an invoice Squarelet has.
        stripe_needs_3ds.assert_called_once()

    def test_a_line_added_to_a_live_subscription_is_kept(
        self,
        organization_factory,
        user_factory,
        plan_factory,
        subscription_item_factory,
        stripe_needs_3ds,
    ):
        user = user_factory()
        organization = organization_factory(admins=[user])
        subscription_item_factory(
            subscription__organization=organization,
            subscription__subscription_id="sub_3ds",
            plan=plan_factory(annual=False, base_price=10, minimum_users=1),
        )
        plan = for_sale(plan_factory(annual=False, base_price=40, minimum_users=1))

        with pytest.raises(PaymentActionRequired):
            organization.add_subscription(plan, None, user, payment_method="card")

        assert organization.subscription_items.filter(plan=plan).exists()
        stripe_needs_3ds.assert_called_once()


@pytest.mark.django_db()
def test_an_abandoned_challenge_ends_the_subscription(
    subscription_item_factory, plan_factory, mocker
):
    mocker.patch("squarelet.organizations.tasks.send_cache_invalidations")
    item = subscription_item_factory(
        subscription__subscription_id="sub_3ds",
        plan=plan_factory(annual=False, base_price=40, minimum_users=1),
    )

    tasks.handle_subscription_updated({"id": "sub_3ds", "status": "incomplete_expired"})

    assert not Subscription.objects.filter(pk=item.subscription_id).exists()
