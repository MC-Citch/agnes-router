"""
API 适配器 —— 基类 + 各后端实现。

新增后端只需：
  1. 继承 BaseAdapter
  2. 实现 _chat_impl()
  3. 在 SmartRouter 中注册
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import AsyncOpenAI, OpenAI, APIError, RateLimitError, APIConnectionError, APITimeoutError

from config import cfg, BackendConfig


# ============================================================
# 工具函数
# ============================================================

def _build_http_client(proxy: str | None = None, timeout: float = 120.0) -> httpx.Client:
    """构建带代理的同步 HTTP 客户端。"""
    kwargs: dict[str, Any] = dict(timeout=timeout)
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def _build_async_http_client(proxy: str | None = None, timeout: float = 120.0) -> httpx.AsyncClient:
    """构建带代理的异步 HTTP 客户端。"""
    kwargs: dict[str, Any] = dict(timeout=timeout)
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)


def _to_raw_base64(image_data: str) -> str:
    """将图片数据转为纯 Base64（去掉 data URI 前缀）。

    Agnes 视频 API 的 image 参数接受纯 Base64 或 HTTP URL，
    但不接受带前缀的 data URI（data:image/...;base64,...）。
    """
    if image_data.startswith("data:") and ";base64," in image_data:
        return image_data.split(";base64,", 1)[1]
    return image_data  # 已经是纯 Base64 或 HTTP URL


# ============================================================
# 通用响应
# ============================================================

@dataclass
class LLMResponse:
    content: str
    model: str
    backend: str
    finish_reason: str = "stop"
    raw: Any = None


class AdapterError(Exception):
    """适配器层统一异常"""
    def __init__(self, message: str, backend: str = "", retryable: bool = False):
        super().__init__(message)
        self.backend = backend
        self.retryable = retryable


# ============================================================
# 基类
# ============================================================

class BaseAdapter(ABC):
    """后端适配器基类。子类只需实现 _chat_impl。"""

    # 子类覆盖
    RETRY_MAX: int = 3
    RETRY_DELAY: float = 1.0  # 秒

    def __init__(self, backend_cfg: BackendConfig):
        self.cfg = backend_cfg
        http_client = _build_http_client(proxy=self.cfg.proxy)
        self._client = OpenAI(
            api_key=self.cfg.api_key,
            base_url=self.cfg.base_url,
            http_client=http_client,
        )
        # 异步客户端，避免阻塞事件循环
        async_http_client = _build_async_http_client(proxy=self.cfg.proxy)
        self._async_client = AsyncOpenAI(
            api_key=self.cfg.api_key,
            base_url=self.cfg.base_url,
            http_client=async_http_client,
        )

    @property
    def name(self) -> str:
        return self.cfg.name

    @property
    def key(self) -> str:
        return self.cfg.key

    @property
    def is_configured(self) -> bool:
        return self.cfg.is_configured

    # ---- 公开接口 ----

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        enable_search: bool = False,
    ) -> LLMResponse:
        """对话补全，带自动重试。"""
        model = model or self.cfg.model

        if not self.is_configured:
            raise AdapterError(
                f"{self.name} 未配置 API Key，请检查 .env",
                backend=self.key, retryable=False,
            )

        last_error: Exception | None = None
        for attempt in range(1, self.RETRY_MAX + 1):
            try:
                return await self._chat_impl(messages, model, temperature, max_tokens, enable_search)
            except RateLimitError as e:
                last_error = e
                if attempt < self.RETRY_MAX:
                    delay = self.RETRY_DELAY * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
            except (APIConnectionError, APITimeoutError) as e:
                last_error = e
                if attempt < self.RETRY_MAX:
                    delay = self.RETRY_DELAY * attempt
                    await asyncio.sleep(delay)
            except APIError as e:
                raise AdapterError(
                    f"{self.name} API 错误: {e}", backend=self.key, retryable=False,
                ) from e

        raise AdapterError(
            f"{self.name} 重试 {self.RETRY_MAX} 次后仍失败: {last_error}",
            backend=self.key, retryable=True,
        )

    @abstractmethod
    async def _chat_impl(
        self, messages: list[dict[str, Any]], model: str,
        temperature: float, max_tokens: int,
        enable_search: bool = False,
    ) -> LLMResponse:
        """子类实现具体的 API 调用。"""
        ...

    # ---- 可选能力 ----

    def supports_images(self) -> bool:
        """是否支持图片生成。"""
        return bool(self.cfg.image_model)

    async def generate_image(
        self, prompt: str, model: str | None = None,
        size: str = "1024x1024", n: int = 1,
    ) -> list[str]:
        """图片生成（子类可覆盖）。默认使用 OpenAI 兼容接口。"""
        if not self.cfg.image_model:
            raise AdapterError(
                f"{self.name} 不支持图片生成", backend=self.key, retryable=False,
            )
        model = model or self.cfg.image_model
        resp = self._client.images.generate(model=model, prompt=prompt, size=size, n=n)
        return [
            img.url or img.b64_json or ""
            for img in resp.data
        ]


# ============================================================
# Agnes 适配器
# ============================================================

class AgnesAdapter(BaseAdapter):
    """Agnes AI：文本 + 视觉 + 图片生成 + 视频生成"""

    RETRY_MAX = 2  # Agnes 免费额度少，少重试

    def __init__(self):
        super().__init__(cfg.agnes)
        # 复用常驻的裸 AsyncClient（带连接池 + keep-alive），
        # 图片/视频每次请求不再新建 TCP/TLS 连接，省几百毫秒握手开销。
        self._raw_http = _build_async_http_client(proxy=self.cfg.proxy, timeout=120)

    def _get_raw_http(self) -> httpx.AsyncClient:
        """返回共享的裸 HTTP 客户端（已建连接池，多次请求复用）。"""
        return self._raw_http

    async def _chat_impl(
        self, messages, model, temperature, max_tokens, enable_search=False,
    ) -> LLMResponse:
        resp = await self._async_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            backend=self.key,
            finish_reason=choice.finish_reason or "stop",
            raw=resp,
        )

    # ---- 图片生成（覆盖基类，改用 HTTP POST 支持 extra_body） ----

    async def generate_image(
        self, prompt: str, model: str | None = None,
        size: str = "1K", n: int = 1,
        ratio: str | None = None,
        return_base64: bool = False,
        reference_images: list[str] | None = None,
        negative_prompt: str | None = None,
    ) -> list[str]:
        """图片生成（支持参考图 + 反向提示词 + Size/Ratio 档位系统）。

        Args:
            prompt: 生成描述
            size: 尺寸档位，推荐 1K / 2K / 3K / 4K
            ratio: 宽高比，如 16:9 / 1:1 / 9:16 等
            return_base64: 文生图时是否返回 Base64
            reference_images: 参考图列表（Data URI 或 HTTP URL），最多 4 张
            negative_prompt: 反向提示词（拼接到 prompt 末尾）
        """
        if not self.cfg.image_model:
            raise AdapterError(
                f"{self.name} 不支持图片生成", backend=self.key, retryable=False,
            )
        model = model or self.cfg.image_model

        # 反向提示词 → prompt 工程（Agnes 图片 API 不支持 negative_prompt 参数）
        if negative_prompt:
            prompt = (
                f"{prompt}. IMPORTANT: Do NOT include any of the following: {negative_prompt}"
            )

        # 构建请求体
        body: dict[str, Any] = {
            "model": model, "prompt": prompt, "size": size, "n": n,
        }
        if ratio:
            body["ratio"] = ratio
        if return_base64:
            body["return_base64"] = True

        if reference_images:
            # 参考图放在 extra_body.image，同时指定 response_format
            body["extra_body"] = {
                "image": reference_images,
                "response_format": "url",
            }

        client = self._get_raw_http()
        resp = await client.post(
            f"{self.cfg.base_url}/images/generations",
            json=body,
            headers={
                "Authorization": f"Bearer {self.cfg.api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            img.get("url") or img.get("b64_json") or ""
            for img in data.get("data", [])
        ]

    # ---- 视频生成 ----

    async def generate_video(
        self, prompt: str, model: str | None = None,
        negative_prompt: str | None = None,
        reference_images: list[str] | None = None,
        mode: str | None = None,
        seconds: str | int | None = None,
        aspect_ratio: str | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """视频生成（Agnes Video 2.5 Flash，免费）。

        新版 API 契约（与旧版 v2.0 完全不同）：
          - 必传 `mode`：text（文生视频）/ keyframe（首尾帧）/ reference（多参考）
          - `seconds`：时长 4-12 秒，默认 5
          - `aspect_ratio`：画幅，如 "16:9" / "9:16"
          - keyframe 模式用 first_frame / last_frame 传首尾帧
          - reference 模式用 images（纯 Base64 或 URL，最多 5 张）
          - 注意：width / height / num_frames / frame_rate 是禁止字段，不能传

        视频 API 限流严格（1次/分钟），带自动重试。
        """
        model = model or self.cfg.video_model

        # 根据是否带参考图，自动推断 mode
        if not mode:
            mode = "reference" if reference_images else "text"
        if reference_images and mode == "text":
            mode = "reference"
        if reference_images and mode == "keyframe" and len(reference_images) >= 2:
            mode = "reference"  # 多张只能走 reference

        # 反向提示词 → 拼进 prompt（Flash 无 negative_prompt 参数）
        if negative_prompt:
            prompt = f"{prompt}. IMPORTANT: Do NOT include any of the following: {negative_prompt}"

        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "mode": mode,
        }

        # 时长（4-12 秒，默认 5）
        body["seconds"] = str(seconds or "5")

        # 画幅
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio

        if seed is not None:
            body["seed"] = seed

        # 参考图（纯 Base64，不带 data URI 前缀）
        if reference_images:
            raw = [_to_raw_base64(img) for img in reference_images][:5]
            if mode == "keyframe":
                body["first_frame"] = raw[0]
                if len(raw) >= 2:
                    body["last_frame"] = raw[1]
            else:
                # reference 模式
                body["images"] = raw

        # 带重试的请求（视频 API 限流 1次/分钟）
        last_error = None

        client = self._get_raw_http()
        for attempt in range(4):  # 最多重试 4 次
            resp = await client.post(
                f"{self.cfg.base_url}/videos",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.cfg.api_key}",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code == 429:
                # 提取真实错误信息(免费额度耗尽等)
                try:
                    err = resp.json().get("error", {})
                    last_error = (
                        f"视频生成限流/额度不足: {err.get('message', '请稍后重试')}"
                    )
                except Exception:
                    last_error = "视频生成限流（1次/分钟），请等待后重试"
                retry_after = resp.headers.get("Retry-After", "60")
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = 60.0
                wait = min(wait, 90)
                if attempt < 3:
                    await asyncio.sleep(wait)
                    continue
                else:
                    break  # 重试耗尽，用干净的 last_error 提示，而非原始 429

            if resp.status_code == 503:
                # 503 队列满 / 无可用渠道 — 提取真实错误信息并等待后重试
                err_body = {}
                try:
                    err_body = resp.json()
                except Exception:
                    pass
                msg = err_body.get("error", {}).get("message") or err_body.get("message") or ""
                code = err_body.get("code", "")
                if "queue" in msg.lower() or "full" in msg.lower() or "queue_full" in code:
                    last_error = "视频服务端队列已满，请等待 1-2 分钟后重试"
                elif "channel" in msg.lower() or "not_found" in code:
                    last_error = f"视频模型当前不可用: {msg or code or resp.text[:200]}"
                else:
                    last_error = f"视频服务端暂时不可用（503）: {msg or '请稍后重试'}"
                try:
                    if "retry_after" in err_body:
                        wait = min(float(err_body["retry_after"]), 60.0)
                    else:
                        wait = 15.0
                except Exception:
                    wait = 15.0
                if attempt < 3:
                    await asyncio.sleep(wait)
                    continue
                else:
                    break  # 重试耗尽，用干净的 last_error 提示，而非原始 503

            if resp.status_code == 200:
                return resp.json()

            # 其他错误
            try:
                err_body = resp.json()
                err_msg = err_body.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text[:300]
            raise AdapterError(
                f"{self.name} 视频生成失败 (HTTP {resp.status_code}): {err_msg}",
                backend=self.key, retryable=False,
            )

        raise AdapterError(
            last_error or "视频生成失败，请稍后重试",
            backend=self.key, retryable=True,
        )

    async def get_video_status(self, task_id: str) -> dict[str, Any]:
        """查询视频生成任务状态，带限流重试。"""
        client = self._get_raw_http()
        for attempt in range(3):
            resp = await client.get(
                f"{self.cfg.base_url}/videos/{task_id}",
                headers={"Authorization": f"Bearer {self.cfg.api_key}"},
            )
            if resp.status_code == 429:
                # 被限流，等待后重试
                retry_after = resp.headers.get("Retry-After", "10")
                wait = float(retry_after) if retry_after.isdigit() else 10.0
                await asyncio.sleep(min(wait, 30))
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()  # 重试耗尽，抛出异常
        return resp.json()


# ============================================================
# DeepSeek 适配器
# ============================================================

class DeepSeekAdapter(BaseAdapter):
    """DeepSeek：专注复杂推理，长上下文，支持联网搜索"""

    RETRY_MAX = 3

    def __init__(self):
        super().__init__(cfg.deepseek)

    async def _chat_impl(
        self, messages, model, temperature, max_tokens, enable_search=False,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # 启用联网搜索
        if enable_search:
            kwargs["extra_body"] = {"enable_search": True}

        resp = await self._async_client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        content = choice.message.content or ""
        # 清理 DeepSeek 搜索返回的 tool_call 内部标记
        import re as _re
        content = _re.sub(r'<tool_call>.*?</tool_call>', '', content, flags=_re.DOTALL)
        content = _re.sub(r'</?tool_call>', '', content)
        content = content.strip()
        return LLMResponse(
            content=content,
            model=resp.model,
            backend=self.key,
            finish_reason=choice.finish_reason or "stop",
            raw=resp,
        )
