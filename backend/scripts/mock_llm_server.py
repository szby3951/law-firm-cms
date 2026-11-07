"""本地 OpenAI 兼容 mock 服务：无外网 / 无 API Key 时验证 9.2 接入层。

用途（仅开发自测，不属于业务代码）：

- 验证流式解析：逐字返回 SSE，可设置每段间隔；
- 验证 JSON 模式：请求带 ``response_format`` 时返回 JSON 对象；
- 验证重试：``MOCK_FAIL_ONCE=2`` 让前两次请求返回 500；
- 验证鉴权/降级：``MOCK_API_KEY`` 不匹配返回 401，``MOCK_STATUS`` 强制指定状态码；
- 验证配置驱动：把收到的 ``model`` 回显出来，换 ``LLM_MODEL`` 即可看出是否生效。

启动::

    cd backend
    .venv/Scripts/python.exe scripts/mock_llm_server.py          # 监听 127.0.0.1:8099
    LLM_BASE_URL=http://127.0.0.1:8099/v1 LLM_API_KEY=test-key \
        .venv/Scripts/python.exe scripts/ai_smoke.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Mock OpenAI API", docs_url=None, redoc_url=None)

API_KEY = os.getenv("MOCK_API_KEY", "test-key")
DELAY_MS = int(os.getenv("MOCK_DELAY_MS", "30"))
ALWAYS_STATUS = int(os.getenv("MOCK_STATUS", "0"))  # 非 0 时所有请求直接返回该状态
FAIL_ONCE = int(os.getenv("MOCK_FAIL_ONCE", "0"))  # 前 N 次请求返回 500
REJECT_JSON_FORMAT = (
    os.getenv("MOCK_REJECT_JSON_FORMAT", "") == "1"
)  # 模拟不支持 json_object

_state = {"requests": 0, "failures_done": 0}
_recent: list[dict[str, object]] = []


def _log_request(body: dict) -> dict:
    messages = body.get("messages") or []
    record = {
        "model": body.get("model"),
        "stream": bool(body.get("stream")),
        "response_format": body.get("response_format"),
        "temperature": body.get("temperature"),
        "max_tokens": body.get("max_tokens"),
        "messages": len(messages),
        "last_user": (messages[-1].get("content", "") if messages else "")[:60],
    }
    _recent.append(record)
    del _recent[:-10]
    return record


def _answer(record: dict, body: dict) -> str:
    """按请求类型编一个可识别的回答，便于断言。"""
    joined = str([m.get("content") for m in body.get("messages", [])])
    wants_json = bool(body.get("response_format")) or "JSON" in joined
    if wants_json:
        return json.dumps(
            {
                "mock": True,
                "model": record["model"],
                "level": "high",
                "risks": [{"clause": "第1条", "advice": "建议补充违约责任"}],
            },
            ensure_ascii=False,
        )
    # RAG 问答（9.3）：回答里带 [n] 引用，用来验证引用解析与原文回链
    if "【参考资料】" in joined:
        refs = len(re.findall(r"\[\d+\]\s*《", joined))
        cited = "、".join(f"[{i}]" for i in range(1, min(refs, 3) + 1)) or "[1]"
        return (
            "结论：约定的违约金过分高于实际损失的，可以请求人民法院或仲裁机构适当减少。"
            f"{cited}\n\n"
            "依据：违约金以补偿为主、惩罚为辅，约定金额显著超过实际损失的，"
            "法院会结合合同履行情况、当事人过错程度等因素综合衡量。\n\n"
            "建议：收集实际损失证据（付款凭证、同期市场价格、替代交易成本），"
            "在诉讼或仲裁中主动提出调整请求。\n"
        )
    return f"我是 {record['model']}（本地 mock），已收到：{record['last_user']}"


@app.get("/v1/models")
async def models(authorization: str = Header(default="")) -> JSONResponse:
    if authorization != f"Bearer {API_KEY}":
        return JSONResponse({"error": {"message": "Invalid API key"}}, status_code=401)
    return JSONResponse(
        {"object": "list", "data": [{"id": "mock-chat", "object": "model"}]}
    )


@app.get("/v1/_requests")
async def recent_requests() -> JSONResponse:
    """查看最近请求，用于断言「配置是否真的传到了模型」."""
    return JSONResponse({"total": _state["requests"], "recent": _recent})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: str = Header(default="")):
    _state["requests"] += 1

    if ALWAYS_STATUS:
        return JSONResponse(
            {"error": {"message": f"mock 强制返回 {ALWAYS_STATUS}"}},
            status_code=ALWAYS_STATUS,
        )
    if authorization != f"Bearer {API_KEY}":
        return JSONResponse(
            {"error": {"message": "Authentication Fails, Your api key is invalid"}},
            status_code=401,
        )
    if _state["failures_done"] < FAIL_ONCE:
        _state["failures_done"] += 1
        return JSONResponse(
            {"error": {"message": "mock 的临时故障，模拟 5xx 重试"}}, status_code=500
        )

    body = await request.json()
    if REJECT_JSON_FORMAT and body.get("response_format"):
        return JSONResponse(
            {"error": {"message": "response_format is not supported by this model"}},
            status_code=400,
        )
    record = _log_request(body)
    text = _answer(record, body)
    delay = DELAY_MS / 1000

    if not body.get("stream"):
        return JSONResponse(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": record["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": len(text)},
            }
        )

    async def event_stream():
        # 先发一个只带 role 的分片，模仿真实服务（客户端应跳过空 delta）
        yield 'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        for char in text:
            payload = {"choices": [{"delta": {"content": char}, "index": 0}]}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if delay:
                await asyncio.sleep(delay)
        yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Mock-Start": str(time.time())},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI 兼容 mock 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()

    import uvicorn

    print(f"mock LLM 监听 http://{args.host}:{args.port}/v1（key={API_KEY}）")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
