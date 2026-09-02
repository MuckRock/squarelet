# Django
from django.core.files.base import ContentFile
from django.core.management import call_command

# Standard Library
from io import StringIO

# Third Party
import pytest
import stripe


def _save_receipt(charge, content):
    charge.receipt_pdf.save(f"{charge.charge_id}.pdf", ContentFile(content), save=True)


@pytest.mark.django_db()
class TestCleanupBadReceiptPdfs:
    """Tests for the cleanup_bad_receipt_pdfs management command"""

    def test_leaves_real_pdfs_alone(self, charge_factory, mocker):
        charge = charge_factory(charge_id="ch_good")
        _save_receipt(charge, b"%PDF-1.4 real pdf content")
        mocked_delay = mocker.patch(
            "squarelet.organizations.management.commands"
            ".cleanup_bad_receipt_pdfs.download_receipt_pdf.delay"
        )

        call_command("cleanup_bad_receipt_pdfs", stdout=StringIO())

        charge.refresh_from_db()
        assert charge.receipt_pdf
        mocked_delay.assert_not_called()

    def test_clears_and_requeues_html_receipts(self, charge_factory, mocker):
        charge = charge_factory(charge_id="ch_bad")
        _save_receipt(charge, b"<!DOCTYPE html><html>not a pdf</html>")
        mock_charge = mocker.MagicMock(receipt_url="https://stripe.com/receipt/ch_bad")
        mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_charge_service.return_value.retrieve.return_value = (
            mock_charge
        )
        mocked_delay = mocker.patch(
            "squarelet.organizations.management.commands"
            ".cleanup_bad_receipt_pdfs.download_receipt_pdf.delay"
        )

        call_command("cleanup_bad_receipt_pdfs", stdout=StringIO())

        charge.refresh_from_db()
        assert not charge.receipt_pdf
        mocked_delay.assert_called_once_with(
            charge.pk, "https://stripe.com/receipt/ch_bad"
        )

    def test_dry_run_does_not_modify_anything(self, charge_factory, mocker):
        charge = charge_factory(charge_id="ch_bad_dry")
        _save_receipt(charge, b"<!DOCTYPE html><html>not a pdf</html>")
        mocked_delay = mocker.patch(
            "squarelet.organizations.management.commands"
            ".cleanup_bad_receipt_pdfs.download_receipt_pdf.delay"
        )

        call_command("cleanup_bad_receipt_pdfs", "--dry-run", stdout=StringIO())

        charge.refresh_from_db()
        assert charge.receipt_pdf
        mocked_delay.assert_not_called()

    def test_org_filter_scopes_query(
        self, charge_factory, organization_factory, mocker
    ):
        other_org = organization_factory()
        charge = charge_factory(charge_id="ch_other_org", organization=other_org)
        _save_receipt(charge, b"<!DOCTYPE html><html>not a pdf</html>")
        mocked_delay = mocker.patch(
            "squarelet.organizations.management.commands"
            ".cleanup_bad_receipt_pdfs.download_receipt_pdf.delay"
        )

        call_command(
            "cleanup_bad_receipt_pdfs",
            "--org",
            "some-other-slug",
            stdout=StringIO(),
        )

        charge.refresh_from_db()
        assert charge.receipt_pdf
        mocked_delay.assert_not_called()

    def test_continues_past_stripe_error(self, charge_factory, mocker):
        charge = charge_factory(charge_id="ch_stripe_error")
        _save_receipt(charge, b"<!DOCTYPE html><html>not a pdf</html>")
        mocker.patch(
            "squarelet.organizations.models.payment.get_payment_provider"
        ).return_value.get_charge_service.return_value.retrieve.side_effect = (
            stripe.InvalidRequestError("not found", param=None)
        )
        mocked_delay = mocker.patch(
            "squarelet.organizations.management.commands"
            ".cleanup_bad_receipt_pdfs.download_receipt_pdf.delay"
        )
        out = StringIO()

        call_command("cleanup_bad_receipt_pdfs", stdout=out, stderr=StringIO())

        charge.refresh_from_db()
        # left untouched since we couldn't get a fresh receipt_url
        assert charge.receipt_pdf
        mocked_delay.assert_not_called()
        assert "1 error" in out.getvalue()
