"""Inbound speech to text: faster-whisper `small` on CPU, Spanish, a two-minute cap (PLAN D16).

Nothing here loads a model at import: `manage.py work` pays for it on the first voice note, and
a deployment without the weights still boots. The whole audio path is CPU-only, no ffmpeg pass.
"""

from django.conf import settings

_MODELS = {}


class RejectedAudio(Exception):
    """The audio cannot become a transcript; the lawyer gets one Spanish line instead."""


class TooLong(RejectedAudio):
    """Past the cap: the note is not worth minutes of CPU, and the lawyer is told so."""

    def __init__(self, duration):
        self.duration = duration
        super().__init__(f"la nota dura {duration:.0f} s")


class Unreadable(RejectedAudio):
    """Not audio we can decode, or nothing spoken in it."""


def _model(name):
    from faster_whisper import WhisperModel

    if name not in _MODELS:
        _MODELS[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _MODELS[name]


def transcribe(path):
    """(text, model name) for one voice note, or `RejectedAudio` when it cannot be read."""
    name = settings.STT_MODEL
    try:
        model = _model(name)
        segments, info = model.transcribe(
            str(path), language=settings.STT_LANGUAGE, vad_filter=True
        )
        if info.duration and info.duration > settings.STT_MAX_SECONDS:
            raise TooLong(info.duration)
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except RejectedAudio:
        raise
    except Exception as exc:  # a broken container must not retry three times
        raise Unreadable(f"{type(exc).__name__}: {exc}") from exc
    if not text:
        raise Unreadable("la nota no trae voz")
    return text, name
