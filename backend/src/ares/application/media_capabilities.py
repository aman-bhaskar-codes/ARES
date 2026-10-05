from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LocalMediaRuntimeCapabilities:
    ffmpeg: bool
    whisper_runtime: bool
    whisper_model: bool

    @property
    def media_decode_ready(self) -> bool:
        return self.ffmpeg

    @property
    def transcription_ready(self) -> bool:
        return self.media_decode_ready and self.whisper_runtime and self.whisper_model

    @property
    def video_processing_ready(self) -> bool:
        # Frame sampling/probing remains useful without an ASR model. Videos with
        # audio will then publish an explicit transcript gap rather than being rejected.
        return self.media_decode_ready


def probe_local_media_runtime(
    *,
    ffmpeg_binary: str,
    ffprobe_binary: str,
    whisper_model_path: str,
) -> LocalMediaRuntimeCapabilities:
    """Probe only local prerequisites; never downloads models or starts subprocesses."""

    model_root = Path(whisper_model_path).expanduser()
    # faster-whisper's local CTranslate2 snapshots always carry the serialized
    # model and config. Treating an empty/mis-mounted directory as ready would
    # admit jobs that can only fail later in the ASR subprocess. Optional
    # tokenizer/preprocessor files vary by converted model, so do not require
    # them here.
    whisper_model_ready = (
        model_root.is_dir()
        and (model_root / "model.bin").is_file()
        and (model_root / "config.json").is_file()
    )
    return LocalMediaRuntimeCapabilities(
        ffmpeg=bool(shutil.which(ffmpeg_binary) and shutil.which(ffprobe_binary)),
        whisper_runtime=importlib.util.find_spec("faster_whisper") is not None,
        whisper_model=whisper_model_ready,
    )
