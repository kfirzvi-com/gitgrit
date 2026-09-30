"""Noise directories: only directory components count, never the basename."""
from django.test import SimpleTestCase

from app.domain.architecture.paths import in_dirs, is_noise


class NoisePathTests(SimpleTestCase):
    def test_a_file_named_like_a_noise_dir_survives(self):
        self.assertFalse(is_noise("scripts/build"))
        self.assertFalse(is_noise("vendor"))

    def test_a_noise_dir_component_is_skipped(self):
        self.assertTrue(is_noise("apps/api/node_modules/express/index.js"))
        self.assertTrue(is_noise("dist/main.js"))

    def test_in_dirs_on_a_nested_path(self):
        self.assertTrue(in_dirs("deploy/k8s/base/app.yaml", {"k8s"}))
        self.assertFalse(in_dirs("deploy/k8s/base/app.yaml", {"base.yaml", "app.yaml", "helm"}))
