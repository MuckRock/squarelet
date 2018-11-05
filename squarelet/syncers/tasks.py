
# Django
from celery.task import task

# Standard Library
import logging

# Third Party
from requests.exceptions import RequestException

# Local
from .syncers import syncers

logger = logging.getLogger(__name__)


@task(name="sync.sync")
def sync(model_name, action, args):
    """Sync a model to all client sites"""
    logger.info("sync: %s %s %s", model_name, action, args)
    for site in syncers[model_name].sites.keys():
        sync_site.delay(model_name, site, action, args)


@task(
    name="sync.sync_site",
    autoretry_for=(RequestException,),
    retry_backoff=True,
    retry_kwargs={"max_retires": 10},
)
def sync_site(model_name, site, action, args):
    """Sync a model to a single client site"""
    logger.info("sync site: %s %s %s %s", model_name, site, action, args)
    syncer = syncers[model_name](site, *args)
    response = syncer.action(action)
    if response.status_code >= 400:
        logger.error(
            "sync site response: %s %s", response.status_code, response.content
        )
    else:
        logger.info("sync site response: %s %s", response.status_code, response.content)
