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
    # Deliberately not "media" - that prefix is served publicly over
    # CloudFront. Keeping private objects on their own prefix lets the
    # CloudFront distribution restrict viewer access (via a trusted key
    # group) on this path alone, without requiring signed URLs for public
    # media too. See AWS_CLOUDFRONT_KEY_ID/AWS_CLOUDFRONT_KEY in
    # config/settings/production.py - both must be set for url() to return
    # a signed CloudFront URL; otherwise it falls back to an unsigned one.
    location = "private"
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
