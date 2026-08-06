# Django
from django.conf import settings
from django.core.files.storage import default_storage

# Third Party
from storages.backends.s3boto3 import S3Boto3Storage

# pylint: disable=abstract-method


class MediaRootS3BotoStorage(S3Boto3Storage):
    location = "media"
    file_overwrite = False


class PrivateMediaStorage(S3Boto3Storage):
    location = "media"
    default_acl = "private"
    file_overwrite = False
    querystring_auth = True


def private_storage():
    """Return PrivateMediaStorage in production, default storage
    otherwise.

    Using a callable avoids instantiating S3 storage in environments
    where AWS credentials are not configured (local dev, tests).
    """
    if hasattr(settings, "AWS_STORAGE_BUCKET_NAME"):
        return PrivateMediaStorage()
    return default_storage
