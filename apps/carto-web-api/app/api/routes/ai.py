from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/ai", tags=["ai"])


class AiChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class AiChatRequest(BaseModel):
    messages: list[AiChatMessage] = Field(min_length=1, max_length=30)
    context: Optional[str] = Field(default=None, max_length=8000)


class AiChatResponse(BaseModel):
    message: AiChatMessage
    model: str


@router.post("/chat", response_model=AiChatResponse)
def chat(request: Request, payload: AiChatRequest) -> AiChatResponse:
    settings = request.app.state.settings
    if not settings.deepseek_api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "DeepSeek API key is not configured. Set DEEPSEEK_API_KEY or "
                "GYYGEO_WEB_API_DEEPSEEK_API_KEY."
            ),
        )

    system_prompt = (
        "你是 gyygeo 制图工作台里的 AI 助手，帮助用户查找遥感数据、解释 bbox、"
        "规划制图流程、排查服务状态，并给出简洁可执行的中文建议。"
    )
    if payload.context:
        system_prompt = f"{system_prompt}\n\n当前页面上下文：\n{payload.context}"

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(
        {"role": message.role, "content": message.content}
        for message in payload.messages[-16:]
        if message.role != "system"
    )

    request_body = json.dumps(
        {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": 0.3,
            "stream": False,
        }
    ).encode("utf-8")
    upstream_request = urllib.request.Request(
        f"{settings.deepseek_base_url}/chat/completions",
        data=request_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "gyygeo-carto-web-api/0.1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            upstream_request,
            timeout=settings.deepseek_timeout_seconds,
        ) as response:
            upstream_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"DeepSeek request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="DeepSeek returned invalid JSON.") from exc

    try:
        content = upstream_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="DeepSeek response did not include a message.") from exc

    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=502, detail="DeepSeek response message was empty.")

    return AiChatResponse(
        message=AiChatMessage(role="assistant", content=content.strip()),
        model=settings.deepseek_model,
    )
