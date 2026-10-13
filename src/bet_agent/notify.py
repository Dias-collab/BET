from __future__ import annotations

import json
import mimetypes
import secrets
import urllib.parse
import urllib.request
from pathlib import Path


class TelegramNotifier:
    def __init__(self, token: str | None, chat_id: str | None):
        self.token = token
        self.chat_id = chat_id

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_text(self, text: str) -> None:
        if not self.configured:
            print(text)
            return
        data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{self.token}/sendMessage", data=data, timeout=30
        ):
            pass

    def send_photo(self, path: Path, caption: str) -> None:
        if not self.configured:
            print(f"{caption}\nСкриншот: {path}")
            return
        boundary = f"----betagent{secrets.token_hex(12)}"
        parts: list[bytes] = []

        def field(name: str, value: str) -> None:
            parts.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"), b"\r\n",
            ])

        field("chat_id", str(self.chat_id))
        field("caption", caption)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        parts.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(), path.read_bytes(), b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/sendPhoto",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=60):
            pass

