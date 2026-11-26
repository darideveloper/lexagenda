from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from apps.integrations import stt


def a_model(text=" El cliente firmó el convenio. ", duration=40.0):
    """A stand-in for `WhisperModel`: same call shape, no weights, no download."""
    model = mock.Mock()
    model.transcribe.return_value = (
        iter([SimpleNamespace(text=text)]),
        SimpleNamespace(duration=duration),
    )
    return model


class SttTests(TestCase):
    """One voice note in, one Spanish transcript out, capped at two minutes (PLAN §6.4)."""

    def test_a_spanish_note_comes_back_with_its_model(self):
        model = a_model()
        with mock.patch.object(stt, "_model", return_value=model):
            text, model_name = stt.transcribe("/tmp/nota.ogg")

        self.assertEqual(text, "El cliente firmó el convenio.")
        self.assertEqual(model_name, "small")
        model.transcribe.assert_called_once_with("/tmp/nota.ogg", language="es", vad_filter=True)

    def test_audio_over_two_minutes_is_refused(self):
        model = a_model(duration=121.0)
        with mock.patch.object(stt, "_model", return_value=model):
            with self.assertRaises(stt.TooLong):
                stt.transcribe("/tmp/nota.ogg")

    def test_unreadable_audio_is_refused(self):
        model = mock.Mock()
        model.transcribe.side_effect = ValueError("no decodifica")
        with mock.patch.object(stt, "_model", return_value=model):
            with self.assertRaises(stt.Unreadable):
                stt.transcribe("/tmp/nota.ogg")

    def test_silence_is_refused(self):
        model = a_model(text="  ")
        with mock.patch.object(stt, "_model", return_value=model):
            with self.assertRaises(stt.Unreadable):
                stt.transcribe("/tmp/nota.ogg")

    def test_the_defaults_are_small_spanish_and_two_minutes(self):
        from django.conf import settings

        self.assertEqual(settings.STT_MODEL, "small")
        self.assertEqual(settings.STT_LANGUAGE, "es")
        self.assertEqual(settings.STT_MAX_SECONDS, 120)

    def test_the_real_path_loads_the_model_lazily(self):
        """Importing the module never loads weights; the first voice note pays for them."""
        self.assertFalse(hasattr(stt, "WhisperModel"))
        self.assertEqual(stt._MODELS, {})
