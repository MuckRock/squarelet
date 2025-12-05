# Squarelet
from squarelet.organizations.models import ReceiptEmail


class TestReceiptEmail:
    """Unit tests for ReceiptEmail model"""

    def test_str(self):
        receipt_email = ReceiptEmail(email="email@example.com")
        assert str(receipt_email) == f"Receipt Email: <{receipt_email.email}>"
