# Django
from django.core.files.storage import get_storage_class

# Third Party
from storages.backends.s3boto3 import S3Boto3Storage

# pylint: disable=abstract-method


class CachedS3Boto3Storage(S3Boto3Storage):
    """
    S3 storage backend that saves the files locally, too.
    """

    location = "static"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.local_storage = get_storage_class(
            "compressor.storage.CompressorFileStorage"
        )()

    def save(self, name, content):
        # pylint: disable=protected-access, arguments-differ
        self.local_storage._save(name, content)
        super().save(name, self.local_storage._open(name))
        return name


class MediaRootS3BotoStorage(S3Boto3Storage):
    location = "media"
    file_overwrite = False
