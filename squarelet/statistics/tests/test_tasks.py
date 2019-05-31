# Standard Library
from datetime import date, timedelta

# Third Party
import pytest

# Local
from .. import tasks
from ..models import Statistics


@pytest.mark.django_db()
def test_store_statistics():
    tasks.store_statistics()
    stats = Statistics.objects.first()
    assert stats.date == date.today() - timedelta(1)
    assert stats.total_users == 0
    assert stats.total_orgs == 0
