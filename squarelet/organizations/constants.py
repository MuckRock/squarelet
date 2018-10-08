
# Local
from .choices import OrgType

MIN_USERS = {OrgType.free: 1, OrgType.pro: 1, OrgType.basic: 5, OrgType.plus: 5}

BASE_PRICE = {OrgType.basic: 100, OrgType.plus: 200}

PRICE_PER_USER = {OrgType.basic: 10, OrgType.plus: 20}

BASE_REQUESTS = {OrgType.free: 0, OrgType.pro: 20, OrgType.basic: 50, OrgType.plus: 50}

EXTRA_REQUESTS_PER_USER = {
    OrgType.free: 0,
    OrgType.pro: 0,
    OrgType.basic: 5,
    OrgType.plus: 5,
}

BASE_PAGES = {
    OrgType.free: 250,
    OrgType.pro: 2500,
    OrgType.basic: 5000,
    OrgType.plus: 20000,
}

EXTRA_PAGES_PER_USER = {
    OrgType.free: 0,
    OrgType.pro: 0,
    OrgType.basic: 1000,
    OrgType.plus: 5000,
}
