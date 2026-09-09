import io
import wave
from datetime import date
from pathlib import Path

import av
import pytest

from local_transcriber import (
    Database,
    DuplicateMediaError,
    InvalidMediaError,
    MediaImportSettings,
    MediaLibrary,
    MediaTooLargeError,
    Repository,
    RuntimePaths,
    Transcript,
    TranscriptionJob,
    UnsupportedMediaError,
    sanitize_filename,
)


def _wav_bytes(*, sample: int = 0, frames: int = 800) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(sample.to_bytes(2, "little", signed=True) * frames)
    return output.getvalue()


@pytest.fixture
def library(tmp_path: Path) -> MediaLibrary:
    paths = RuntimePaths((tmp_path / "runtime").resolve())
    database = Database(paths.database)
    database.initialize()
    return MediaLibrary(Repository(database), paths)


def test_import_valid_media_by_stream_and_list(library: MediaLibrary) -> None:
    subject = library.create_subject("Língua Portuguesa")
    recording = library.import_stream(
        io.BytesIO(_wav_bytes()),
        original_name="Aula çãõ?.WAV",
        title="Fonética brasileira",
        subject_id=subject.id,
        lesson_date=date(2026, 3, 4),
    )

    stored = library.paths.resolve_relative(recording.relative_path)
    assert stored.read_bytes() == _wav_bytes()
    assert recording.original_name == "Aula çãõ_.wav"
    assert recording.duration_seconds == pytest.approx(0.1)
    assert recording.relative_path.startswith(f"media/2026/{recording.id}/")
    assert not Path(recording.relative_path).is_absolute()
    assert library.list_recordings() == [recording]


def test_import_valid_media_from_controlled_file(library: MediaLibrary, tmp_path: Path) -> None:
    source = tmp_path / "origem.wav"
    source.write_bytes(_wav_bytes(sample=1))
    subject = library.create_subject("Música")

    recording = library.import_file(
        source, title="Som", subject_id=subject.id, lesson_date=date(2026, 1, 2)
    )

    assert recording.original_name == "origem.wav"
    assert library.paths.resolve_relative(recording.relative_path).is_file()


def test_invalid_file_and_unsupported_extension_are_rejected(library: MediaLibrary) -> None:
    subject = library.create_subject("Teste")
    metadata = {
        "title": "Inválido",
        "subject_id": subject.id,
        "lesson_date": date(2026, 1, 1),
    }
    with pytest.raises(InvalidMediaError):
        library.import_stream(io.BytesIO(b"not media"), original_name="fake.mp3", **metadata)
    with pytest.raises(UnsupportedMediaError):
        library.import_stream(io.BytesIO(_wav_bytes()), original_name="audio.exe", **metadata)
    with pytest.raises(UnsupportedMediaError, match="does not match"):
        library.import_stream(io.BytesIO(_wav_bytes()), original_name="disfarce.mp3", **metadata)
    assert library.list_recordings() == []


def test_video_without_audio_is_rejected(library: MediaLibrary, tmp_path: Path) -> None:
    video = tmp_path / "silent.mkv"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("mpeg4", rate=1)
        stream.width = 16
        stream.height = 16
        stream.pix_fmt = "yuv420p"
        frame = av.VideoFrame(16, 16, "yuv420p")
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    subject = library.create_subject("Cinema")

    with pytest.raises(InvalidMediaError, match="audio stream"):
        library.import_file(
            video, title="Vídeo mudo", subject_id=subject.id, lesson_date=date(2026, 1, 1)
        )


def test_duplicate_and_size_limit_are_rejected(library: MediaLibrary) -> None:
    subject = library.create_subject("Biologia")
    content = _wav_bytes()
    metadata = {
        "title": "Células",
        "subject_id": subject.id,
        "lesson_date": date(2026, 5, 1),
    }
    first = library.import_stream(io.BytesIO(content), original_name="one.wav", **metadata)
    with pytest.raises(DuplicateMediaError) as duplicate:
        library.import_stream(io.BytesIO(content), original_name="two.wav", **metadata)
    assert duplicate.value.existing.id == first.id

    limited = MediaLibrary(
        library.repository,
        library.paths,
        settings=MediaImportSettings(max_size_bytes=10, chunk_size_bytes=4),
    )
    with pytest.raises(MediaTooLargeError):
        limited.import_stream(io.BytesIO(content), original_name="large.wav", **metadata)
    assert list(library.paths.media.rglob("*.part")) == []


def test_path_traversal_is_sanitized_and_delete_is_explicit(library: MediaLibrary) -> None:
    assert sanitize_filename("../../CON?.WAV") == "CON_.wav"
    subject = library.create_subject("Segurança")
    recording = library.import_stream(
        io.BytesIO(_wav_bytes(sample=2)),
        original_name="../../fora.wav",
        title="Caminho seguro",
        subject_id=subject.id,
        lesson_date=date(2026, 6, 1),
    )
    stored = library.paths.resolve_relative(recording.relative_path)
    assert stored.is_file()
    assert ".." not in recording.relative_path

    job = library.repository.add_job(
        TranscriptionJob(recording_id=recording.id, engine="test", model_name="artificial")
    )
    transcript = library.repository.add_transcript(
        Transcript(
            recording_id=recording.id,
            job_id=job.id,
            language="pt",
            text="Registro dependente",
        )
    )

    assert library.delete_recording(recording.id) is True
    assert library.delete_recording(recording.id) is False
    assert not stored.exists()
    assert library.repository.get_job(job.id) is None
    assert library.repository.get_transcript(transcript.id) is None
    assert library.list_recordings() == []
