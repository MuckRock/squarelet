# Django
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

# Third Party
import pytest

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

    @pytest.mark.django_db
    def test_stripe_link_with_invoice_id(self, invoice_admin, invoice_factory):
        """Should generate Stripe dashboard link for invoice"""
        invoice = invoice_factory(invoice_id="in_test123")
        link = invoice_admin.stripe_link(invoice)

        assert "https://dashboard.stripe.com/invoices/in_test123" in link
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
    def test_mark_as_paid_action(
        self, invoice_admin, invoice_factory, request_factory, mocker
    ):
        """Should mark open invoices as paid"""
        open_invoice = invoice_factory(status="open")
        paid_invoice = invoice_factory(status="paid")

        request = request_factory.get("/")
        mocker.patch.object(invoice_admin, "message_user")
        queryset = Invoice.objects.filter(id__in=[open_invoice.id, paid_invoice.id])

        invoice_admin.mark_as_paid(request, queryset)

        open_invoice.refresh_from_db()
        paid_invoice.refresh_from_db()

        assert open_invoice.status == "paid"
        assert paid_invoice.status == "paid"  # Should remain paid

    @pytest.mark.django_db
    def test_mark_as_uncollectible_action(
        self, invoice_admin, invoice_factory, request_factory, mocker
    ):
        """Should mark open invoices as uncollectible"""
        open_invoice = invoice_factory(status="open")
        void_invoice = invoice_factory(status="void")

        request = request_factory.get("/")
        mocker.patch.object(invoice_admin, "message_user")
        queryset = Invoice.objects.filter(id__in=[open_invoice.id, void_invoice.id])

        invoice_admin.mark_as_uncollectible(request, queryset)

        open_invoice.refresh_from_db()
        void_invoice.refresh_from_db()

        assert open_invoice.status == "uncollectible"
        assert void_invoice.status == "void"  # Should remain void


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
