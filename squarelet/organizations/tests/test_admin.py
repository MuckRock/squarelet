# Django
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, override_settings

# Third Party
import pytest
import stripe

# Squarelet
from squarelet.organizations.admin import InvoiceAdmin, OrganizationAdmin
from squarelet.organizations.models import Invoice, Organization


class TestInvoiceAdmin:
    """Tests for Invoice admin interface"""

    @pytest.fixture
    def invoice_admin(self):
        return InvoiceAdmin(Invoice, AdminSite())

    @pytest.fixture
    def request_factory(self):
        return RequestFactory()

    @override_settings(ENV="prod")
    @pytest.mark.django_db
    def test_stripe_link_with_invoice_id(self, invoice_admin, invoice_factory):
        """Should generate Stripe dashboard link for invoice"""
        invoice = invoice_factory(invoice_id="in_test123")
        link = invoice_admin.stripe_link(invoice)

        assert "https://dashboard.stripe.com/invoices/in_test123" in link
        assert 'target="_blank"' in link
        assert "View in Stripe" in link

    @override_settings(ENV="staging")
    @pytest.mark.django_db
    def test_stripe_test_link_with_invoice_id(self, invoice_admin, invoice_factory):
        """Should generate Stripe test-mode dashboard link for invoice"""
        invoice = invoice_factory(invoice_id="in_test123")
        link = invoice_admin.stripe_link(invoice)

        assert "https://dashboard.stripe.com/test/invoices/in_test123" in link
        assert 'target="_blank"' in link
        assert "View in Stripe" in link

    @pytest.mark.django_db
    def test_stripe_link_without_invoice_id(self, invoice_admin, invoice_factory):
        """Should return dash when no invoice_id"""
        invoice = invoice_factory(invoice_id="")
        link = invoice_admin.stripe_link(invoice)

        assert link == "-"

    @pytest.mark.django_db
    def test_get_amount_display(self, invoice_admin, invoice_factory):
        """Should format amount in dollars"""
        invoice = invoice_factory(amount=12345)  # $123.45
        amount_display = invoice_admin.get_amount(invoice)

        assert amount_display == "$123.45"

    @pytest.mark.django_db
    def test_mark_as_paid_action_syncs_to_stripe(
        self, invoice_admin, invoice_factory, request_factory, mocker
    ):
        """Should mark open invoices as paid and sync to Stripe"""
        open_invoice = invoice_factory(status="open", invoice_id="in_test123")

        request = request_factory.get("/")
        message_user_mock = mocker.patch.object(invoice_admin, "message_user")

        # Mock Stripe API calls
        mock_stripe_invoice = mocker.Mock()
        stripe_retrieve_mock = mocker.patch(
            "stripe.Invoice.retrieve", return_value=mock_stripe_invoice
        )

        queryset = Invoice.objects.filter(id=open_invoice.id)
        invoice_admin.mark_as_paid(request, queryset)

        open_invoice.refresh_from_db()

        # Verify Stripe was called
        stripe_retrieve_mock.assert_called_once_with("in_test123")
        mock_stripe_invoice.pay.assert_called_once()

        # Verify local DB was updated
        assert open_invoice.status == "paid"

        # Verify success message
        message_user_mock.assert_called_once()
        assert "1 invoice(s) marked as paid" in str(message_user_mock.call_args)

    @pytest.mark.django_db
    def test_mark_as_paid_handles_stripe_error(
        self, invoice_admin, invoice_factory, request_factory, mocker
    ):
        """Should handle Stripe API errors gracefully"""
        open_invoice = invoice_factory(status="open", invoice_id="in_test456")

        request = request_factory.get("/")
        message_user_mock = mocker.patch.object(invoice_admin, "message_user")

        # Mock Stripe API to raise an error
        stripe_error = stripe.error.InvalidRequestError(
            "Invoice is already paid", "invoice"
        )
        mocker.patch("stripe.Invoice.retrieve", side_effect=stripe_error)

        # Mock logger
        logger_mock = mocker.patch("squarelet.organizations.admin.logger")

        queryset = Invoice.objects.filter(id=open_invoice.id)
        invoice_admin.mark_as_paid(request, queryset)

        open_invoice.refresh_from_db()

        # Verify local DB was NOT updated
        assert open_invoice.status == "open"

        # Verify error was logged
        logger_mock.error.assert_called_once()
        assert "in_test456" in str(logger_mock.error.call_args)

        # Verify error message shown to admin (only error message, no success)
        assert message_user_mock.call_count == 1
        assert "could not be updated in Stripe" in str(message_user_mock.call_args)

    @pytest.mark.django_db
    def test_mark_as_paid_only_updates_open_invoices(
        self, invoice_admin, invoice_factory, request_factory, mocker
    ):
        """Should only mark open invoices as paid"""
        open_invoice = invoice_factory(status="open", invoice_id="in_open")
        paid_invoice = invoice_factory(status="paid", invoice_id="in_paid")

        request = request_factory.get("/")
        mocker.patch.object(invoice_admin, "message_user")

        # Mock Stripe API calls
        mock_stripe_invoice = mocker.Mock()
        stripe_retrieve_mock = mocker.patch(
            "stripe.Invoice.retrieve", return_value=mock_stripe_invoice
        )

        queryset = Invoice.objects.filter(id__in=[open_invoice.id, paid_invoice.id])
        invoice_admin.mark_as_paid(request, queryset)

        open_invoice.refresh_from_db()
        paid_invoice.refresh_from_db()

        # Only open invoice should trigger Stripe call
        stripe_retrieve_mock.assert_called_once_with("in_open")
        mock_stripe_invoice.pay.assert_called_once()

        assert open_invoice.status == "paid"
        assert paid_invoice.status == "paid"

    @pytest.mark.django_db
    def test_get_readonly_fields_for_existing_open_invoice(
        self, invoice_admin, invoice_factory, request_factory
    ):
        """Should make all fields readonly and include actions for open invoice"""
        invoice = invoice_factory(status="open")
        request = request_factory.get("/")

        readonly_fields = invoice_admin.get_readonly_fields(request, obj=invoice)

        # All editable fields should be readonly when editing
        expected_readonly = (
            "get_amount",
            "updated_at",
            "stripe_link",
            "invoice_id",
            "organization",
            "subscription",
            "amount",
            "status",
            "due_date",
            "last_overdue_email_sent",
            "created_at",
        )
        assert set(readonly_fields) == set(expected_readonly)

    @pytest.mark.django_db
    def test_get_readonly_fields_for_existing_paid_invoice(
        self, invoice_admin, invoice_factory, request_factory
    ):
        """Should make all fields readonly without actions for non-open invoice"""
        invoice = invoice_factory(status="paid")
        request = request_factory.get("/")

        readonly_fields = invoice_admin.get_readonly_fields(request, obj=invoice)

        # All editable fields should be readonly when editing
        expected_readonly = (
            "get_amount",
            "updated_at",
            "stripe_link",
            "invoice_id",
            "organization",
            "subscription",
            "amount",
            "status",
            "due_date",
            "last_overdue_email_sent",
            "created_at",
        )
        assert set(readonly_fields) == set(expected_readonly)

    @pytest.mark.django_db
    def test_get_readonly_fields_for_new_invoice(self, invoice_admin, request_factory):
        """Should allow editing when creating new invoice"""
        request = request_factory.get("/")

        readonly_fields = invoice_admin.get_readonly_fields(request, obj=None)

        # Only standard readonly fields when creating
        expected_readonly = (
            "get_amount",
            "updated_at",
            "stripe_link",
        )
        assert set(readonly_fields) == set(expected_readonly)

    @pytest.mark.django_db
    def test_changelist_view_mark_as_paid_single(
        self, invoice_admin, invoice_factory, request_factory, mocker
    ):
        """Should handle single invoice mark as paid action"""
        open_invoice = invoice_factory(status="open", invoice_id="in_single")

        # Mock Stripe API calls
        mock_stripe_invoice = mocker.Mock()
        mocker.patch("stripe.Invoice.retrieve", return_value=mock_stripe_invoice)

        # Mock message_user to avoid message middleware requirement
        mocker.patch.object(invoice_admin, "message_user")

        # Create request with mark_as_paid_single action
        request = request_factory.get(
            "/admin/organizations/invoice/",
            {"action": "mark_as_paid_single", "invoice_id": open_invoice.pk},
        )

        # Call changelist_view
        response = invoice_admin.changelist_view(request)

        # Verify it returns a redirect
        assert response.status_code == 302
        assert (
            f"/admin/organizations/invoice/{open_invoice.pk}/change/"
            in response.headers["Location"]
        )

        # Verify invoice was marked as paid
        open_invoice.refresh_from_db()
        assert open_invoice.status == "paid"


class TestOrganizationAdmin:
    """Tests for Organization admin interface"""

    @pytest.fixture
    def org_admin(self):
        return OrganizationAdmin(Organization, AdminSite())

    @pytest.fixture
    def request_factory(self):
        return RequestFactory()

    @pytest.mark.django_db
    def test_get_queryset_annotates_invoice_data(
        self, org_admin, organization_factory, invoice_factory, request_factory
    ):
        """Should annotate organizations with outstanding invoice count and total"""
        org = organization_factory()
        invoice_factory(organization=org, status="open", amount=10000)
        invoice_factory(organization=org, status="open", amount=20000)
        invoice_factory(organization=org, status="paid", amount=5000)  # Not counted

        request = request_factory.get("/")
        queryset = org_admin.get_queryset(request)
        org_with_annotations = queryset.get(id=org.id)

        assert org_with_annotations.outstanding_invoice_count == 2
        assert org_with_annotations.outstanding_invoice_total == 30000

    @pytest.mark.django_db
    def test_get_outstanding_invoices_display_with_invoices(
        self, org_admin, organization_factory, invoice_factory
    ):
        """Should display count and total for organizations with outstanding invoices"""
        org = organization_factory()
        invoice_factory(organization=org, status="open", amount=12345)
        invoice_factory(organization=org, status="open", amount=67890)

        # Manually annotate for testing
        org.outstanding_invoice_count = 2
        org.outstanding_invoice_total = 80235

        display = org_admin.get_outstanding_invoices(org)

        assert display == "2 ($802.35)"

    @pytest.mark.django_db
    def test_get_outstanding_invoices_display_without_invoices(
        self, org_admin, organization_factory
    ):
        """Should display dash for organizations with no outstanding invoices"""
        org = organization_factory()

        # Manually annotate for testing
        org.outstanding_invoice_count = 0
        org.outstanding_invoice_total = None

        display = org_admin.get_outstanding_invoices(org)

        assert display == "-"
