# Django
from django.utils.translation import gettext_lazy as _

# Third Party
from djchoices import ChoiceItem, DjangoChoices


class ChangeLogReason(DjangoChoices):
    created = ChoiceItem(0, _("Created"))
    updated = ChoiceItem(1, _("Updated"))
    failed = ChoiceItem(2, _("Failed"))
    credit_card = ChoiceItem(3, _("Credit Card"))


class RelationshipType(DjangoChoices):
    member = ChoiceItem(0, _("Member"))
    child = ChoiceItem(1, _("Child"))


COUNTRY_CHOICES = (
    ("US", _("United States of America")),
    ("CA", _("Canada")),
)

STATE_CHOICES = (
    ("AK", _("Alaska")),
    ("AL", _("Alabama")),
    ("AR", _("Arkansas")),
    ("AZ", _("Arizona")),
    ("CA", _("California")),
    ("CO", _("Colorado")),
    ("CT", _("Connecticut")),
    ("DC", _("District of Columbia")),
    ("DE", _("Delaware")),
    ("FL", _("Florida")),
    ("GA", _("Georgia")),
    ("HI", _("Hawaii")),
    ("IA", _("Iowa")),
    ("ID", _("Idaho")),
    ("IL", _("Illinois")),
    ("IN", _("Indiana")),
    ("KS", _("Kansas")),
    ("KY", _("Kentucky")),
    ("LA", _("Louisiana")),
    ("MA", _("Massachusetts")),
    ("MD", _("Maryland")),
    ("ME", _("Maine")),
    ("MI", _("Michigan")),
    ("MN", _("Minnesota")),
    ("MO", _("Missouri")),
    ("MS", _("Mississippi")),
    ("MT", _("Montana")),
    ("NC", _("North Carolina")),
    ("ND", _("North Dakota")),
    ("NE", _("Nebraska")),
    ("NH", _("New Hampshire")),
    ("NJ", _("New Jersey")),
    ("NM", _("New Mexico")),
    ("NV", _("Nevada")),
    ("NY", _("New York")),
    ("OH", _("Ohio")),
    ("OK", _("Oklahoma")),
    ("OR", _("Oregon")),
    ("PA", _("Pennsylvania")),
    ("RI", _("Rhode Island")),
    ("SC", _("South Carolina")),
    ("SD", _("South Dakota")),
    ("TN", _("Tennessee")),
    ("TX", _("Texas")),
    ("UT", _("Utah")),
    ("VA", _("Virginia")),
    ("VT", _("Vermont")),
    ("WA", _("Washington")),
    ("WI", _("Wisconsin")),
    ("WV", _("West Virginia")),
    ("WY", _("Wyoming")),
    ("AS", _("American Samoa")),
    ("GU", _("Guam")),
    ("MP", _("Northern Mariana Islands")),
    ("PR", _("Puerto Rico")),
    ("VI", _("Virgin Islands")),
    ("AB", _("Alberta")),
    ("BC", _("British Columbia")),
    ("MB", _("Manitoba")),
    ("NB", _("New Brunswick")),
    ("NL", _("Newfoundland and Labrador")),
    ("NT", _("Northwest Territories")),
    ("NS", _("Nova Scotia")),
    ("NU", _("Nunavut")),
    ("ON", _("Ontario")),
    ("PE", _("Prince Edward Island")),
    ("QC", _("Quebec")),
    ("SK", _("Saskatchewan")),
    ("YT", _("Yukon")),
)

CHANGE_STATUS_CHOICES = (
    ("pending", _("Pending")),
    ("accepted", _("Accepted")),
    ("rejected", _("Rejected")),
)
