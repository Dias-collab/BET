from pathlib import Path

from bet_agent.config import _load_key_values


def test_plain_two_line_olimp_credentials(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OLIMP_LOGIN", raising=False)
    monkeypatch.delenv("OLIMP_PASSWORD", raising=False)
    path = tmp_path / "password.txt"
    path.write_text("user123\nsecret456\n", encoding="utf-8")
    _load_key_values(path)
    import os

    assert os.environ["OLIMP_LOGIN"] == "user123"
    assert os.environ["OLIMP_PASSWORD"] == "secret456"
