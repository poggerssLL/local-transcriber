from datetime import date
from pathlib import Path

import pytest

from local_transcriber import (
    SCHEMA_VERSION,
    Database,
    ExportedArtifact,
    JobStatus,
    Recording,
    Repository,
    Segment,
    Subject,
    Transcript,
    TranscriptionJob,
    Word,
)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "nested" / "test.sqlite3")
    database.initialize()
    return database


def make_recording(subject: Subject, *, title: str = "Álgebra — Aula ção") -> Recording:
    return Recording(
        title=title,
        subject_id=subject.id,
        lesson_date=date(2026, 9, 9),
        original_name="aula 01.m4a",
        sha256="a" * 64,
        size_bytes=123456,
        media_format="M4A",
        duration_seconds=61.25,
        relative_path="media/2026/aula-01.m4a",
    )


def test_database_creation_and_idempotent_migration(database: Database) -> None:
    assert database.path.is_file()
    assert database.schema_version() == SCHEMA_VERSION
    database.initialize()
    assert database.schema_version() == SCHEMA_VERSION


def test_essential_operations_and_restart_preserve_unicode(database: Database) -> None:
    repository = Repository(database)
    subject = repository.add_subject(Subject(name="Física quântica 日本語"))
    recording = repository.add_recording(make_recording(subject))
    job = repository.add_job(
        TranscriptionJob(recording_id=recording.id, engine="faster-whisper", model_name="small")
    )
    repository.update_job_status(job.id, JobStatus.RUNNING)
    repository.update_job_status(job.id, JobStatus.SUCCEEDED)
    transcript = repository.add_transcript(
        Transcript(
            recording_id=recording.id,
            job_id=job.id,
            language="pt",
            text="Olá, mundo — 日本語",
            segments=(
                Segment(
                    ordinal=0,
                    start_seconds=0,
                    end_seconds=1.2,
                    text="Olá, mundo",
                    words=(Word(text="Olá", start_seconds=0, end_seconds=0.4, probability=0.99),),
                ),
            ),
        )
    )
    artifact = repository.add_artifact(
        ExportedArtifact(
            transcript_id=transcript.id, kind="srt", relative_path="exports/aula-01.srt"
        )
    )

    restarted = Repository(Database(database.path))
    restarted.database.initialize()
    assert restarted.get_subject(subject.id) == subject
    assert restarted.get_recording(recording.id) == recording
    loaded = restarted.get_transcript(transcript.id)
    assert loaded is not None
    assert loaded.text == "Olá, mundo — 日本語"
    assert loaded.segments[0].words[0].text == "Olá"
    assert restarted.list_artifacts(transcript.id) == [artifact]


def test_queries_are_parameterized_against_injection(database: Database) -> None:
    repository = Repository(database)
    malicious = Subject(name="x'); DROP TABLE subjects; --")
    repository.add_subject(malicious)
    assert repository.get_subject(malicious.id) == malicious
    assert len(repository.list_subjects()) == 1


def test_filter_recordings_uses_exact_parameter(database: Database) -> None:
    repository = Repository(database)
    subject = repository.add_subject(Subject(name="História"))
    repository.add_recording(make_recording(subject))
    assert repository.list_recordings("' OR 1=1 --") == []
    assert repository.list_recordings(subject.id)[0].title.startswith("Álgebra")


def test_invalid_states_and_values(database: Database) -> None:
    with pytest.raises(ValueError):
        Subject(name="   ")
    with pytest.raises(ValueError, match="sha256"):
        Recording(
            title="A",
            subject_id="s",
            lesson_date=date.today(),
            original_name="a.mp3",
            sha256="bad",
            size_bytes=1,
            media_format="mp3",
            relative_path="media/a.mp3",
        )
    with pytest.raises(ValueError, match="timestamps"):
        Segment(ordinal=0, start_seconds=2, end_seconds=1, text="inválido")
    with pytest.raises(ValueError, match="probability"):
        Word(text="x", start_seconds=0, end_seconds=1, probability=2)

    repository = Repository(database)
    subject = repository.add_subject(Subject(name="Química"))
    recording = repository.add_recording(make_recording(subject))
    job = repository.add_job(
        TranscriptionJob(recording_id=recording.id, engine="faster-whisper", model_name="tiny")
    )
    with pytest.raises(ValueError, match="transition"):
        repository.update_job_status(job.id, JobStatus.SUCCEEDED)
    repository.update_job_status(job.id, JobStatus.RUNNING)
    with pytest.raises(ValueError, match="error message"):
        repository.update_job_status(job.id, JobStatus.FAILED)


def test_foreign_keys_are_enforced(database: Database) -> None:
    repository = Repository(database)
    with pytest.raises(Exception, match="FOREIGN KEY"):
        repository.add_recording(
            Recording(
                title="Órfã",
                subject_id="missing",
                lesson_date=date.today(),
                original_name="x.wav",
                sha256="b" * 64,
                size_bytes=0,
                media_format="wav",
                relative_path="media/x.wav",
            )
        )
