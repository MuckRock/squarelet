# Import all views to maintain backward compatibility with existing imports
# Local
from .admin import Create, Merge
from .detail import Detail, List, autocomplete
from .domains import ManageDomains
from .members import InvitationAccept, ManageMembers
from .profile import RequestProfileChange, ReviewProfileChange, Update
from .subscription import (
    ChargeDetail,
    PDFChargeDetail,
    UpdateSubscription,
    stripe_webhook,
)

__all__ = [
    # Detail views
    "Detail",
    "List",
    "autocomplete",
    # Subscription views
    "UpdateSubscription",
    "ChargeDetail",
    "PDFChargeDetail",
    "stripe_webhook",
    # Profile views
    "Update",
    "RequestProfileChange",
    "ReviewProfileChange",
    # Member views
    "ManageMembers",
    "InvitationAccept",
    # Domain views
    "ManageDomains",
    # Admin views
    "Create",
    "Merge",
]
