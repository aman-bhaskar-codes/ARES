from __future__ import annotations

from pathlib import Path

from ares.application import media_capabilities


def test_media_probe_does_not_treat_empty_model_directory_as_ready(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(media_capabilities.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(media_capabilities.importlib.util, "find_spec", lambda name: object())

    result = media_capabilities.probe_local_media_runtime(
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
        whisper_model_path=str(tmp_path),
    )

    assert result.ffmpeg is True
    assert result.whisper_runtime is True
    assert result.whisper_model is False
    assert result.transcription_ready is False


def test_media_probe_requires_ct2_model_and_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(media_capabilities.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(media_capabilities.importlib.util, "find_spec", lambda name: object())
    (tmp_path / "model.bin").write_bytes(b"model")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")

    result = media_capabilities.probe_local_media_runtime(
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
        whisper_model_path=str(tmp_path),
    )

    assert result.whisper_model is True
    assert result.transcription_ready is True


def test_video_processing_can_be_ready_without_whisper_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(media_capabilities.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(media_capabilities.importlib.util, "find_spec", lambda name: None)

    result = media_capabilities.probe_local_media_runtime(
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
        whisper_model_path=str(tmp_path / "missing"),
    )

    assert result.video_processing_ready is True
    assert result.transcription_ready is False
