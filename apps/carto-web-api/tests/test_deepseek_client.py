from __future__ import annotations

from fastapi import HTTPException

from app.api.routes.agent import _deepseek_chat_completion


class _TimeoutResponse:
    def __enter__(self) -> "_TimeoutResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        raise TimeoutError("read timed out")


def test_deepseek_completion_read_timeout_returns_http_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _TimeoutResponse(),
    )

    try:
        _deepseek_chat_completion(
            settings=type(
                "Settings",
                (),
                {
                    "deepseek_model": "deepseek-test",
                    "deepseek_base_url": "https://example.test",
                    "deepseek_api_key": "test-key",
                    "deepseek_timeout_seconds": 1,
                },
            )(),
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.1,
        )
    except HTTPException as exc:
        assert exc.status_code == 502
        assert "timed out" in str(exc.detail)
    else:
        raise AssertionError("Expected HTTPException")
