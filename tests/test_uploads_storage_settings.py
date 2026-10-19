"""Where upload projects' archives are stored: S3 when a bucket is named,
else a local directory (gitgrit.settings.uploads_storage)."""
from django.test import SimpleTestCase
from django.utils.module_loading import import_string

from gitgrit.settings import uploads_storage


class UploadsStorageTests(SimpleTestCase):
    def test_a_bucket_means_s3_with_the_host_role(self):
        config = uploads_storage("acme-uploads", "eu-north-1", "/unused")
        self.assertEqual(config["BACKEND"], "storages.backends.s3.S3Storage")
        options = config["OPTIONS"]
        self.assertEqual(options["bucket_name"], "acme-uploads")
        self.assertEqual(options["region_name"], "eu-north-1")
        # No keys: boto3 finds the VM role's credentials itself.
        self.assertNotIn("access_key", options)
        self.assertNotIn("secret_key", options)

    def test_the_s3_options_are_ones_the_backend_accepts(self):
        config = uploads_storage("acme-uploads", "eu-north-1", "/unused")
        storage = import_string(config["BACKEND"])(**config["OPTIONS"])  # no AWS call
        self.assertEqual(storage.bucket_name, "acme-uploads")
        self.assertTrue(storage.file_overwrite)
        self.assertFalse(storage.querystring_auth)

    def test_no_bucket_means_a_local_directory(self):
        config = uploads_storage("", "eu-north-1", "/srv/uploads")
        self.assertEqual(config["BACKEND"], "django.core.files.storage.FileSystemStorage")
        self.assertEqual(config["OPTIONS"], {"location": "/srv/uploads"})
