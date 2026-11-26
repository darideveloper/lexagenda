import tempfile
from pathlib import Path

import yaml
from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = Path(settings.BASE_DIR)


class ConfigLoaderTests(SimpleTestCase):
    def test_reads_instance_settings(self):
        from config.loader import load_config

        cfg = load_config(BASE_DIR / "config.yaml")

        self.assertEqual(cfg["name"], "Despacho de prueba")
        self.assertEqual(cfg["delivery_mode"], "auto")
        self.assertEqual(cfg["kinds"]["visita"], {"duration": 60, "buffer": 15})
        self.assertEqual(cfg["caps"]["hourly"], 20)
        self.assertEqual(cfg["reminders"], [7, 3, 1])

    def test_rejects_unknown_delivery_mode(self):
        from config.loader import ConfigError, load_config

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(yaml.safe_dump({"name": "x", "delivery_mode": "telepathy"}))
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_settings_are_mexico_city_postgres(self):
        self.assertTrue(settings.USE_TZ)
        self.assertEqual(settings.TIME_ZONE, "America/Mexico_City")
        self.assertEqual(settings.LANGUAGE_CODE, "es-mx")
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(settings.CONFIG["delivery_mode"], "auto")


class DeployFilesTests(SimpleTestCase):
    def test_compose_is_web_db_gowa_without_redis_or_celery(self):
        text = (BASE_DIR / "docker-compose.yml").read_text()
        compose = yaml.safe_load(text)

        self.assertEqual(set(compose["services"]), {"web", "db", "gowa"})
        self.assertNotIn("redis", text.lower())
        self.assertNotIn("celery", text.lower())
        self.assertNotIn("ports", compose["services"]["gowa"])

    def test_dockerfile_exists(self):
        self.assertTrue((BASE_DIR / "Dockerfile").is_file())
