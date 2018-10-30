# Local
from .choices import Plan

PRICE_PER_REQUEST = 5

MIN_USERS = {Plan.free: 1, Plan.pro: 1, Plan.basic: 5, Plan.plus: 5}

BASE_PRICE = {Plan.basic: 100, Plan.plus: 200}

PRICE_PER_USER = {Plan.basic: 10, Plan.plus: 20}

BASE_REQUESTS = {Plan.free: 0, Plan.pro: 20, Plan.basic: 50, Plan.plus: 50}

EXTRA_REQUESTS_PER_USER = {Plan.free: 0, Plan.pro: 0, Plan.basic: 5, Plan.plus: 5}

BASE_PAGES = {Plan.free: 250, Plan.pro: 2500, Plan.basic: 5000, Plan.plus: 20000}

EXTRA_PAGES_PER_USER = {Plan.free: 0, Plan.pro: 0, Plan.basic: 1000, Plan.plus: 5000}
