# Django
from django.db import models
from django.utils.translation import gettext_lazy as _

# Disabling linting enforcement of uppercase names,
# which would require much larger code changes.
# This is to provide backwards compatibility

# pylint:disable = invalid-name


class ChangeLogReason(models.IntegerChoices):
    created = 0, _("Created")
    updated = 1, _("Updated")
    failed = 2, _("Failed")
    credit_card = 3, _("Credit Card")


class RelationshipType(models.IntegerChoices):
    member = 0, _("Member")
    child = 1, _("Child")


class Country(models.TextChoices):
    US = "US", _("United States of America")
    CA = "CA", _("Canada")


COUNTRY_CHOICES = Country.choices


class State(models.TextChoices):
    AK = "AK", _("Alaska")
    AL = "AL", _("Alabama")
    AR = "AR", _("Arkansas")
    AZ = "AZ", _("Arizona")
    CA = "CA", _("California")
    CO = "CO", _("Colorado")
    CT = "CT", _("Connecticut")
    DC = "DC", _("District of Columbia")
    DE = "DE", _("Delaware")
    FL = "FL", _("Florida")
    GA = "GA", _("Georgia")
    HI = "HI", _("Hawaii")
    IA = "IA", _("Iowa")
    ID = "ID", _("Idaho")
    IL = "IL", _("Illinois")
    IN = "IN", _("Indiana")
    KS = "KS", _("Kansas")
    KY = "KY", _("Kentucky")
    LA = "LA", _("Louisiana")
    MA = "MA", _("Massachusetts")
    MD = "MD", _("Maryland")
    ME = "ME", _("Maine")
    MI = "MI", _("Michigan")
    MN = "MN", _("Minnesota")
    MO = "MO", _("Missouri")
    MS = "MS", _("Mississippi")
    MT = "MT", _("Montana")
    NC = "NC", _("North Carolina")
    ND = "ND", _("North Dakota")
    NE = "NE", _("Nebraska")
    NH = "NH", _("New Hampshire")
    NJ = "NJ", _("New Jersey")
    NM = "NM", _("New Mexico")
    NV = "NV", _("Nevada")
    NY = "NY", _("New York")
    OH = "OH", _("Ohio")
    OK = "OK", _("Oklahoma")
    OR = "OR", _("Oregon")
    PA = "PA", _("Pennsylvania")
    RI = "RI", _("Rhode Island")
    SC = "SC", _("South Carolina")
    SD = "SD", _("South Dakota")
    TN = "TN", _("Tennessee")
    TX = "TX", _("Texas")
    UT = "UT", _("Utah")
    VA = "VA", _("Virginia")
    VT = "VT", _("Vermont")
    WA = "WA", _("Washington")
    WI = "WI", _("Wisconsin")
    WV = "WV", _("West Virginia")
    WY = "WY", _("Wyoming")

    # US Territories
    AS = "AS", _("American Samoa")
    GU = "GU", _("Guam")
    MP = "MP", _("Northern Mariana Islands")
    PR = "PR", _("Puerto Rico")
    VI = "VI", _("Virgin Islands")

    # Canadian Provinces & Territories
    AB = "AB", _("Alberta")
    BC = "BC", _("British Columbia")
    MB = "MB", _("Manitoba")
    NB = "NB", _("New Brunswick")
    NL = "NL", _("Newfoundland and Labrador")
    NT = "NT", _("Northwest Territories")
    NS = "NS", _("Nova Scotia")
    NU = "NU", _("Nunavut")
    ON = "ON", _("Ontario")
    PE = "PE", _("Prince Edward Island")
    QC = "QC", _("Quebec")
    SK = "SK", _("Saskatchewan")
    YT = "YT", _("Yukon")


STATE_CHOICES = State.choices


class ChangeStatus(models.TextChoices):
    pending = "pending", _("Pending")
    accepted = "accepted", _("Accepted")
    rejected = "rejected", _("Rejected")


CHANGE_STATUS_CHOICES = ChangeStatus.choices