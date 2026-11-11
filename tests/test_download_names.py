"""Portable names retain titles without turning them into paths or headers."""

import pytest

from local_transcriber.download_names import download_filename


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Algebra 21/8", "Algebra 21-8.md"),
        ("Álgebra", "Álgebra.md"),
        ('../Aula\\1:"teste"\r\n', "-Aula-1--teste---.md"),
        ("...", "transcricao.md"),
        ("CON", "_CON.md"),
        ("LPT1.texto", "_LPT1.texto.md"),
    ],
)
def test_portable_title(title, expected):
    assert download_filename(title, "md") == expected


def test_long_unicode_title_fits_filesystem_limit():
    result = download_filename("漢" * 400, "resumo.json")
    assert len(result.encode("utf-8")) < 255
    assert result.endswith(".resumo.json")
