# Standard Library
from unittest.mock import Mock


class TestSubscription:
    """Unit tests for the Subscription model"""

    def test_str(self, subscription_factory):
        subscription = subscription_factory.build()
        assert (
            str(subscription)
            == f"Subscription: {subscription.organization} to {subscription.plan.name}"
        )

    def test_stripe_subscription(self, subscription_factory, mocker):
        mocked = mocker.patch("stripe.Subscription.retrieve")
        stripe_subscription = "stripe_subscription"
        mocked.return_value = stripe_subscription
        subscription_id = "subscription_id"
        subscription = subscription_factory.build(subscription_id=subscription_id)
        assert subscription.stripe_subscription == stripe_subscription

    def test_stripe_subscription_empty(self, subscription_factory):
        subscription = subscription_factory.build()
        assert subscription.stripe_subscription is None

    def test_start(self, subscription_factory, professional_plan_factory, mocker):
        plan = professional_plan_factory.build()
        subscription = subscription_factory.build(plan=plan)
        mocked = Mock()
        mocker.patch(
            "squarelet.organizations.models.organization.Organization.customer",
            return_value=mocked,
        )
        subscription.start()
        mocked.stripe_customer.subscriptions.create.assert_called_with(
            items=[
                {
                    "plan": subscription.plan.stripe_id,
                    "quantity": subscription.organization.max_users,
                }
            ],
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=None,
        )
        assert (
            subscription.subscription_id
            == mocked.stripe_customer.subscriptions.create.return_value.id
        )

    def test_start_existing(self, subscription_factory, mocker):
        """If there is an existing subscription, do not start another one"""
        subscription = subscription_factory.build()
        mocked = mocker.patch("squarelet.organizations.models.Organization.customer")
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        subscription.start()
        mocked.subscriptions.create.assert_not_called()

    def test_start_free(self, subscription_factory, mocker):
        """If there is an existing subscription, do not start another one"""
        subscription = subscription_factory.build()
        mocked = mocker.patch("squarelet.organizations.models.Organization.customer")
        subscription.start()
        mocked.subscriptions.create.assert_not_called()

    def test_cancel(self, subscription_factory, mocker):
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_stripe_subscription = mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription"
        )
        subscription = subscription_factory.build()
        subscription.cancel()
        assert mocked_stripe_subscription.cancel_at_period_end
        mocked_stripe_subscription.save.assert_called()
        assert subscription.cancelled
        mocked_save.assert_called()

    def test_modify_start(
        self, subscription_factory, professional_plan_factory, mocker
    ):
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_start = mocker.patch("squarelet.organizations.models.Subscription.start")
        plan = professional_plan_factory.build()
        subscription = subscription_factory.build()
        subscription.modify(plan)
        mocked_save.assert_called()
        mocked_start.assert_called()

    def test_modify_cancel(
        self, subscription_factory, professional_plan_factory, plan_factory, mocker
    ):
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_stripe_subscription = mocker.patch(
            "squarelet.organizations.models.Subscription.stripe_subscription"
        )
        plan = professional_plan_factory.build()
        free_plan = plan_factory.build()
        subscription = subscription_factory.build(plan=plan, subscription_id="id")
        subscription.modify(free_plan)
        mocked_save.assert_called()
        mocked_stripe_subscription.delete.assert_called()
        assert subscription.subscription_id is None

    def test_modify_modify(
        self, subscription_factory, professional_plan_factory, mocker
    ):
        mocked_save = mocker.patch("squarelet.organizations.models.Subscription.save")
        mocked_modify = mocker.patch("stripe.Subscription.modify")
        mocker.patch("squarelet.organizations.models.Subscription.stripe_subscription")
        plan = professional_plan_factory.build()
        subscription = subscription_factory.build(plan=plan)
        subscription.modify(plan)
        mocked_save.assert_called()
        mocked_modify.assert_called_with(
            subscription.subscription_id,
            cancel_at_period_end=False,
            items=[
                {
                    "id": subscription.stripe_subscription["items"]["data"][0].id,
                    "plan": subscription.plan.stripe_id,
                    "quantity": subscription.organization.max_users,
                }
            ],
            billing="charge_automatically",
            metadata={"action": f"Subscription ({plan.name})"},
            days_until_due=None,
        )
