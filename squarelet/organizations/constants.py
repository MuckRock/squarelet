# Local
from .choices import Plan

MIN_USERS = {Plan.free: 1, Plan.pro: 1, Plan.basic: 5, Plan.plus: 5}

BASE_PRICE = {Plan.basic: 100, Plan.plus: 200}

PRICE_PER_USER = {Plan.basic: 10, Plan.plus: 20}
