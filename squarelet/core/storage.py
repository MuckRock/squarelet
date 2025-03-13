# Third Party
from storages.backends.s3boto3 import S3Boto3Storage

# pylint: disable=abstract-method


class MediaRootS3BotoStorage(S3Boto3Storage):
    location = "media"
    file_overwrite = False
