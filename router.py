#!/usr/bin/env python3
"""
不绘来世 - Agnes & DeepSeek 智能路由代理 (LLM Router)

自动分类任务，路由到合适的后端：
  - 图片/视频/简单任务 -> Agnes API（免费全模态）
  - 复杂推理/深度思考   -> DeepSeek v4 Pro

用法:
  python router.py serve              # 启动 Web + API 服务
  python router.py chat "问题"         # CLI 对话
  python router.py image "提示词"      # CLI 生图
  python router.py video "提示词"      # CLI 视频生成
  python router.py chat -b deepseek "问题"  # 手动指定后端
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# ============================================================
# 应用根目录（两套路径）
# - __app_root__：只读静态资源（HTML/CSS/JS/default-bg），
#   打包后指向 PyInstaller 临时解压目录 _MEIPASS
# - __data_root__：可写用户数据（.env / user-data / output），
#   打包后指向 exe 所在目录，确保持久化
# ============================================================
if getattr(sys, "frozen", False):
    __app_root__ = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
    __data_root__ = Path(sys.executable).parent
else:
    __app_root__ = Path(__file__).parent
    __data_root__ = __app_root__

os.environ["APP_ROOT"] = str(__data_root__)

load_dotenv(__data_root__ / ".env")

from config import cfg, ConfigError
from classifier import TaskClassifier, ClassifyResult
from adapters import (
    BaseAdapter, AgnesAdapter, DeepSeekAdapter,
    LLMResponse, AdapterError,
)


# ============================================================
# 后端注册表
# ============================================================

class BackendRegistry:
    """后端注册表 —— 加新后端只需在此注册。"""

    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}
        self._default_models: dict[str, str] = {}

    def register(self, adapter: BaseAdapter, default_model: str = "") -> "BackendRegistry":
        """注册一个后端适配器。"""
        self._adapters[adapter.key] = adapter
        self._default_models[adapter.key] = default_model or adapter.cfg.model
        return self

    def get(self, key: str) -> BaseAdapter:
        """获取适配器。"""
        if key not in self._adapters:
            raise ConfigError(f"未知后端: {key}。可用: {list(self._adapters.keys())}")
        return self._adapters[key]

    @property
    def all_keys(self) -> list[str]:
        return list(self._adapters.keys())

    @property
    def configured_keys(self) -> list[str]:
        return [k for k, a in self._adapters.items() if a.is_configured]

    def get_model(self, key: str) -> str:
        return self._default_models.get(key, "")

    def list_backends(self) -> list[dict[str, Any]]:
        """列出所有后端状态（供 health API 使用）。"""
        return [
            {
                "key": a.key, "name": a.name,
                "configured": a.is_configured,
                "supports_images": a.supports_images(),
            }
            for a in self._adapters.values()
        ]


# 注册所有后端
_backends = BackendRegistry()
_backends.register(AgnesAdapter())
_backends.register(DeepSeekAdapter())


# ============================================================
# 核心路由器
# ============================================================

class SmartRouter:
    """智能路由器：分类 -> 路由 -> 返回结果"""

    def __init__(self, classifier: TaskClassifier | None = None):
        self.backends = _backends
        self.classifier = classifier or TaskClassifier()

    async def route(
        self,
        messages: list[dict[str, Any]],
        backend: str | None = None,
        enable_search: bool = False,
    ) -> tuple[LLMResponse, ClassifyResult]:
        """
        路由消息到合适的后端。

        Args:
            messages: OpenAI 格式的消息列表
            backend: 强制指定后端 key，None = 自动分类
            enable_search: 是否启用联网搜索（仅 DeepSeek 有效）

        Returns:
            (响应, 分类结果)

        Raises:
            ConfigError: 未知后端
            AdapterError: API 调用失败
        """
        # --- 决定后端 ---
        if backend:
            cr = ClassifyResult(
                backend=backend,
                reason=f"用户指定: {backend}",
            )
        elif enable_search:
            cr = ClassifyResult(
                backend="deepseek",
                reason="联网搜索 → DeepSeek",
            )
        else:
            cr = self.classifier.classify(messages)

        # --- 获取适配器 ---
        adapter = self.backends.get(cr.backend)

        # --- 调用 ---
        try:
            resp = await adapter.chat(messages, model=cr.model_override, enable_search=enable_search)
        except AdapterError:
            raise
        except Exception as e:
            raise AdapterError(
                f"调用 {adapter.name} 失败: {e}",
                backend=adapter.key, retryable=False,
            )

        return resp, cr

    async def research_and_generate(
        self,
        user_message: str,
        chat_history: list[dict[str, Any]] | None = None,
    ) -> tuple[LLMResponse, ClassifyResult, str]:
        """深度创作模式：DeepSeek 联网搜索 → Agnes 创意生成。

        流程:
          1. DeepSeek 联网搜索目标角色/主题的关键信息
          2. 将搜索结果注入上下文
          3. Agnes 根据搜索结果完成创意生成（提示词、描写等）

        Args:
            user_message: 用户原始消息
            chat_history: 可选的对话历史

        Returns:
            (最终响应, 分类结果, 研究摘要)
        """
        deepseek = self.backends.get("deepseek")
        agnes = self.backends.get("agnes")

        # ---- Step 1: DeepSeek 联网搜索 ----
        research_prompt = (
            f"请联网搜索并总结以下内容的详细信息。"
            f"重点关注：关键特征、外貌描述、性格特点、背景设定、世界观等。"
            f"请用中文简洁列出要点（200字以内）。\n\n"
            f"需要搜索的内容：{user_message}"
        )
        research_messages = [{"role": "user", "content": research_prompt}]

        research_resp = await deepseek.chat(
            research_messages,
            enable_search=True,
            max_tokens=1024,
        )
        research_text = research_resp.content.strip()

        # ---- Step 2: Agnes 根据研究结果生成 ----
        context = chat_history or []
        generate_prompt = (
            f"以下是你需要的信息（由 DeepSeek 联网搜索获得）：\n\n"
            f"---\n{research_text}\n---\n\n"
            f"请根据以上信息完成用户的请求：\n{user_message}"
        )
        generate_messages = context + [{"role": "user", "content": generate_prompt}]

        generate_resp = await agnes.chat(generate_messages)

        cr = ClassifyResult(
            backend="agnes",
            reason="深度创作: DeepSeek 联网研究 → Agnes 创意生成",
        )

        return generate_resp, cr, research_text

    async def generate_image(
        self, prompt: str, size: str = "1K", n: int = 1, backend: str = "agnes",
        model: str | None = None,
        ratio: str | None = None,
        return_base64: bool = False,
        reference_images: list[str] | None = None,
        negative_prompt: str | None = None,
    ) -> list[str]:
        """图片生成（支持 Size/Ratio 档位 + 参考图 + 反向提示词）。"""
        adapter = self.backends.get(backend)
        if not adapter.supports_images():
            raise AdapterError(
                f"{adapter.name} 不支持图片生成", backend=backend, retryable=False,
            )
        return await adapter.generate_image(
            prompt, model=model, size=size, n=n,
            ratio=ratio,
            return_base64=return_base64,
            reference_images=reference_images,
            negative_prompt=negative_prompt,
        )

    async def generate_video(
        self, prompt: str,
        model: str | None = None,
        negative_prompt: str | None = None,
        reference_images: list[str] | None = None,
        mode: str | None = None,
        seconds: str | int | None = None,
        aspect_ratio: str | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """视频生成 —— Agnes 2.5 Flash（免费）。"""
        agnes = self.backends.get("agnes")
        if isinstance(agnes, AgnesAdapter):
            return await agnes.generate_video(
                prompt, model=model,
                negative_prompt=negative_prompt,
                reference_images=reference_images,
                mode=mode,
                seconds=seconds,
                aspect_ratio=aspect_ratio,
                seed=seed,
            )
        raise AdapterError("视频生成仅 Agnes 支持", backend="agnes", retryable=False)


# ============================================================
# CLI
# ============================================================

def _encode_image_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    ext = Path(path).suffix.lower().lstrip(".")
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}
    return f"data:{mime_map.get(ext, 'image/png')};base64,{data}"


async def _cmd_chat(args: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="router chat")
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--backend", "-b", choices=_backends.all_keys + [None], default=None)
    parser.add_argument("--image", "-i", action="append", default=[])
    parser.add_argument("--system", "-s", default=None)
    opts = parser.parse_args(args)

    prompt_text = " ".join(opts.prompt) or input("请输入问题: ")

    messages: list[dict[str, Any]] = []
    if opts.system:
        messages.append({"role": "system", "content": opts.system})

    if opts.image:
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        for img_path in opts.image:
            content_parts.append({"type": "image_url", "image_url": {"url": _encode_image_to_base64(img_path)}})
        messages.append({"role": "user", "content": content_parts})
    else:
        messages.append({"role": "user", "content": prompt_text})

    router = SmartRouter()
    try:
        resp, cr = await router.route(messages, backend=opts.backend)
    except (AdapterError, ConfigError) as e:
        print(f"\n  错误: {e}\n")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  路由: {cr.backend.upper()}  |  {cr.reason}")
    print(f"{'='*60}\n")
    print(resp.content)
    print()


async def _cmd_image(args: list[str]) -> None:
    import argparse
    import httpx

    parser = argparse.ArgumentParser(prog="router image")
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--size", default="1K", choices=["1K", "2K", "3K", "4K"],
                        help="尺寸档位（默认 1K）")
    parser.add_argument("--ratio", default=None,
                        choices=["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"],
                        help="宽高比（如 16:9）")
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--backend", "-b", default="agnes",
                        choices=[k for k, a in _backends._adapters.items() if a.supports_images()] or ["agnes"])
    parser.add_argument("--reference-image", "-r", action="append", default=None,
                        help="参考图路径（可多次指定，最多 4 张）")
    parser.add_argument("--negative-prompt", "-np", default=None,
                        help="反向提示词（不想要的内容）")
    parser.add_argument("--return-base64", action="store_true",
                        help="返回 Base64 而非 URL")
    opts = parser.parse_args(args)

    prompt = " ".join(opts.prompt) or input("请输入生成提示词: ")
    output_dir = Path(opts.output) if opts.output else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 参考图 → Base64 编码
    reference_images = None
    if opts.reference_image:
        reference_images = [_encode_image_to_base64(p) for p in opts.reference_image]
        print(f"  参考图: {len(reference_images)} 张")

    if opts.negative_prompt:
        print(f"  反向提示词: {opts.negative_prompt}")

    if opts.ratio:
        print(f"  比例: {opts.ratio}")

    print(f"\n  正在生成图片...")
    router = SmartRouter()
    try:
        urls = await router.generate_image(
            prompt, size=opts.size, n=opts.n, backend=opts.backend,
            ratio=opts.ratio,
            return_base64=opts.return_base64,
            reference_images=reference_images,
            negative_prompt=opts.negative_prompt,
        )
    except AdapterError as e:
        print(f"\n  错误: {e}\n")
        sys.exit(1)

    print(f"\n  生成完成！")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for i, url in enumerate(urls):
            if url.startswith("http"):
                ts = int(time.time() * 1000)
                filepath = output_dir / f"agnes_{ts}_{i+1}.png"
                print(f"  [{i+1}] 下载中... {url}")
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    filepath.write_bytes(r.content)
                    print(f"  [{i+1}] 已保存: {filepath}")
                except Exception as e:
                    print(f"  [{i+1}] 下载失败: {e}")
            else:
                ts = int(time.time() * 1000)
                filepath = output_dir / f"agnes_{ts}_{i+1}.png"
                filepath.write_bytes(base64.b64decode(url))
                print(f"  [{i+1}] 已保存: {filepath}")
    print()


def create_app() -> "FastAPI":
    """创建 FastAPI 应用（供 serve 和 desktop 复用）。"""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
    import httpx

    app = FastAPI(
        title="LLM Router",
        description="不绘来世 - Agnes & DeepSeek 智能路由",
        version="3.1.0",
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    router_instance = SmartRouter()

    def _get_user_text(messages: list[dict[str, Any]]) -> str:
        """从消息列表中提取最后一条用户消息的文本。"""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return " ".join(
                        p.get("text", "") for p in c
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
        return ""

    # ---- Chat 端点 ----

    @app.post("/v1/chat/completions")
    async def chat_completions(body: dict[str, Any]):
        messages = body.get("messages", [])
        backend = body.get("backend", None)
        enable_search = body.get("enable_search", False)
        mode = body.get("mode", None)  # "research" = 深度创作模式

        try:
            # 深度创作模式：DeepSeek 搜索 → Agnes 生成
            if mode == "research" and not backend:
                user_msg = _get_user_text(messages)
                history = messages[:-1] if len(messages) > 1 else []

                resp, cr, research_text = await router_instance.research_and_generate(
                    user_message=user_msg,
                    chat_history=history,
                )
                return {
                    "id": "router-research",
                    "object": "chat.completion",
                    "created": 0,
                    "model": resp.model,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": resp.content},
                        "finish_reason": resp.finish_reason,
                    }],
                    "_router": {
                        "backend": cr.backend,
                        "reason": cr.reason,
                        "model_override": cr.model_override,
                    },
                    "_research": {
                        "summary": research_text,
                    },
                }

            resp, cr = await router_instance.route(messages, backend=backend, enable_search=enable_search)
        except AdapterError as e:
            return JSONResponse(
                {"error": {"message": str(e), "backend": e.backend}},
                status_code=502,
            )
        except ConfigError as e:
            return JSONResponse(
                {"error": {"message": str(e)}},
                status_code=400,
            )

        return {
            "id": "router-" + cr.backend,
            "object": "chat.completion",
            "created": 0,
            "model": resp.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": resp.content},
                "finish_reason": resp.finish_reason,
            }],
            "_router": {
                "backend": cr.backend,
                "reason": cr.reason,
                "model_override": cr.model_override,
            },
        }

    # ---- 图片生成 ----

    @app.post("/v1/images/generations")
    async def image_generations(body: dict[str, Any]):
        prompt = body.get("prompt", "")
        size = body.get("size", "1K")
        n = body.get("n", 1)
        backend = body.get("backend", "agnes")
        model = body.get("model", None)
        ratio = body.get("ratio", None)
        return_base64 = body.get("return_base64", False)
        reference_images = body.get("reference_images", None)
        negative_prompt = body.get("negative_prompt", None)

        try:
            urls = await router_instance.generate_image(
                prompt, size=size, n=n, backend=backend, model=model,
                ratio=ratio,
                return_base64=return_base64,
                reference_images=reference_images,
                negative_prompt=negative_prompt,
            )
        except AdapterError as e:
            return JSONResponse({"error": {"message": str(e)}}, status_code=502)

        return {"created": 0, "data": [{"url": u} for u in urls]}

    # ---- 图片保存 ----

    @app.post("/v1/images/save")
    async def image_save(body: dict[str, Any]):
        url = body.get("url", "")
        filename = body.get("filename", None)

        output_dir = __data_root__ / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = f"agnes_{int(time.time() * 1000)}.png"
        filepath = output_dir / filename

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            filepath.write_bytes(r.content)

        return {"success": True, "path": str(filepath), "size": len(r.content)}

    # ---- 视频生成 ----

    @app.post("/v1/video/generations")
    async def video_generations(body: dict[str, Any]):
        """提交视频生成任务，返回任务 ID 供轮询。"""
        prompt = body.get("prompt", "")
        if not prompt:
            return JSONResponse({"error": {"message": "prompt 不能为空"}}, status_code=400)

        model = body.get("model", None)
        negative_prompt = body.get("negative_prompt", None)
        reference_images = body.get("reference_images", None)
        mode = body.get("mode", None)
        seconds = body.get("seconds", None)
        aspect_ratio = body.get("aspect_ratio", None)
        seed = body.get("seed", None)

        try:
            result = await router_instance.generate_video(
                prompt, model=model,
                negative_prompt=negative_prompt,
                reference_images=reference_images,
                mode=mode,
                seconds=seconds,
                aspect_ratio=aspect_ratio,
                seed=seed,
            )
        except AdapterError as e:
            return JSONResponse({"error": {"message": str(e)}}, status_code=502)
        except Exception as e:
            return JSONResponse({"error": {"message": f"视频生成失败: {e}"}}, status_code=500)

        # 兼容多种 Agnes 返回格式
        task_id = result.get("id") or result.get("task_id") or ""
        video_id = result.get("video_id") or task_id
        return {
            "task_id": task_id,
            "video_id": video_id,
            "status": result.get("status", "submitted"),
            "raw": result,
        }

    @app.get("/v1/video/status/{task_id}")
    async def video_status(task_id: str):
        """查询视频生成任务状态。"""
        agnes = _backends.get("agnes")
        if not isinstance(agnes, AgnesAdapter):
            return JSONResponse(
                {"error": {"message": "视频生成仅 Agnes 支持"}}, status_code=400,
            )

        try:
            result = await agnes.get_video_status(task_id)
        except Exception as e:
            return JSONResponse(
                {"error": {"message": f"查询状态失败: {e}"}}, status_code=502,
            )

        return {"task_id": task_id, "raw": result}

    # ---- 视频保存 ----

    @app.post("/v1/video/save")
    async def video_save(body: dict[str, Any]):
        """下载视频到 output 目录。"""
        url = body.get("url", "")
        filename = body.get("filename", None)

        if not url:
            return JSONResponse({"error": {"message": "url 不能为空"}}, status_code=400)

        output_dir = __data_root__ / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = f"agnes_video_{int(time.time() * 1000)}.mp4"
        filepath = output_dir / filename

        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            filepath.write_bytes(r.content)

        return {"success": True, "path": str(filepath), "size": len(r.content)}

    # ---- 健康检查 ----

    @app.get("/health")
    async def health():
        backends = _backends.list_backends()
        return {
            "status": "ok",
            "backends": backends,
            "warnings": cfg.validate(),
        }

    # ---- 后端列表 ----

    @app.get("/v1/backends")
    async def list_backends():
        return {"backends": _backends.list_backends()}

    # ---- 配置管理 API ----

    @app.get("/api/config")
    async def get_config():
        """获取当前 API 配置（隐藏 API Key 中间部分）。"""
        def mask_key(key: str) -> str:
            if not key or len(key) < 8:
                return "****"
            return key[:4] + "•" * (len(key) - 8) + key[-4:]

        return {
            "agnes": {
                "api_key": mask_key(cfg.agnes.api_key),
                "base_url": cfg.agnes.base_url,
                "model": cfg.agnes.model,
                "image_models": cfg.agnes.image_models,
                "video_models": cfg.agnes.video_models,
                "proxy": cfg.agnes.proxy or "",
                "configured": cfg.agnes.is_configured,
            },
            "deepseek": {
                "api_key": mask_key(cfg.deepseek.api_key),
                "base_url": cfg.deepseek.base_url,
                "model": cfg.deepseek.model,
                "proxy": cfg.deepseek.proxy or "",
                "configured": cfg.deepseek.is_configured,
            },
            "server": {
                "host": cfg.host,
                "port": cfg.port,
                "base_url": f"http://{cfg.host}:{cfg.port}",
            },
        }

    @app.post("/api/config")
    async def update_config(body: dict[str, Any]):
        """更新 API 配置并写入 .env 文件。"""
        import sys
        from pathlib import Path

        # 声明全局变量
        global cfg

        env_path = __data_root__ / ".env"

        # 读取现有 .env 内容
        env_content = ""
        if env_path.exists():
            env_content = env_path.read_text(encoding="utf-8")

        # 更新字段
        updates = {
            "AGNES_API_KEY": body.get("agnes_api_key", cfg.agnes.api_key),
            "AGNES_BASE_URL": body.get("agnes_base_url", cfg.agnes.base_url),
            "DEEPSEEK_API_KEY": body.get("deepseek_api_key", cfg.deepseek.api_key),
            "DEEPSEEK_BASE_URL": body.get("deepseek_base_url", cfg.deepseek.base_url),
            "AGNES_PROXY": body.get("agnes_proxy", cfg.agnes.proxy or ""),
            "DEEPSEEK_PROXY": body.get("deepseek_proxy", cfg.deepseek.proxy or ""),
        }

        for key, value in updates.items():
            # 跳过空字符串（用户清空代理 → 写空字符串表示禁用）
            # 但保留非空值
            pattern = rf"^({re.escape(key)})=.*$"
            if re.search(pattern, env_content, re.MULTILINE):
                env_content = re.sub(pattern, rf"\1={value}", env_content, flags=re.MULTILINE)
            else:
                env_content += f"\n{key}={value}\n"

        # 写回 .env
        env_path.write_text(env_content, encoding="utf-8")

        # 直接更新内存中的配置对象
        cfg.agnes.api_key = updates["AGNES_API_KEY"]
        cfg.agnes.base_url = updates["AGNES_BASE_URL"]
        cfg.agnes.proxy = updates["AGNES_PROXY"] or None
        cfg.deepseek.api_key = updates["DEEPSEEK_API_KEY"]
        cfg.deepseek.base_url = updates["DEEPSEEK_BASE_URL"]
        cfg.deepseek.proxy = updates["DEEPSEEK_PROXY"] or None

        return {"success": True, "message": "配置已保存，立即生效"}

    # ---- 背景图片持久化 ----

    @app.post("/api/background")
    async def save_background(body: dict[str, Any]):
        """保存用户自定义背景图片到 user-data 目录。"""
        image_data = body.get("image", "")
        if not image_data:
            return JSONResponse({"error": {"message": "image 不能为空"}}, status_code=400)

        # 解析 data URI (data:image/...;base64,...)
        import base64 as _b64
        import re as _re
        match = _re.match(r"data:image/(\w+);base64,(.+)", image_data)
        if not match:
            return JSONResponse({"error": {"message": "无效的图片格式"}}, status_code=400)

        ext = match.group(1)
        if ext == "jpeg":
            ext = "jpg"
        raw = _b64.b64decode(match.group(2))

        user_data_dir = __data_root__ / "user-data"
        user_data_dir.mkdir(exist_ok=True)
        filepath = user_data_dir / f"bg.{ext}"
        filepath.write_bytes(raw)

        return {"success": True, "url": f"/user-data/bg.{ext}"}

    @app.get("/api/background")
    async def get_background():
        """检查是否有已保存的用户背景图片。"""
        user_data_dir = __data_root__ / "user-data"
        for ext in ("jpg", "jpeg", "png", "webp", "bmp"):
            fp = user_data_dir / f"bg.{ext}"
            if fp.exists():
                return {"url": f"/user-data/bg.{ext}"}
        return {"url": None}

    @app.delete("/api/background")
    async def delete_background():
        """删除用户自定义背景图片。"""
        user_data_dir = __data_root__ / "user-data"
        for ext in ("jpg", "jpeg", "png", "webp", "bmp"):
            fp = user_data_dir / f"bg.{ext}"
            if fp.exists():
                fp.unlink()
        return {"success": True}

    # ---- 设置持久化 API ----

    _settings_path = __data_root__ / "user-data" / "settings.json"

    @app.get("/api/settings")
    async def get_settings():
        """读取用户设置（模糊度、亮度等）。"""
        if _settings_path.exists():
            import json as _json
            try:
                return _json.loads(_settings_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    @app.post("/api/settings")
    async def save_settings(body: dict[str, Any]):
        """保存用户设置到磁盘。"""
        _settings_path.parent.mkdir(exist_ok=True)
        import json as _json
        _settings_path.write_text(_json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return {"success": True}

    @app.delete("/api/settings")
    async def delete_settings():
        """删除用户设置文件。"""
        if _settings_path.exists():
            _settings_path.unlink()
        return {"success": True}

    # ---- 静态文件 ----

    static_dir = __app_root__ / "static"
    static_dir.mkdir(exist_ok=True)

    # 用户数据目录（背景图片等可写文件）
    user_data_dir = __data_root__ / "user-data"
    user_data_dir.mkdir(exist_ok=True)
    app.mount("/user-data", StaticFiles(directory=str(user_data_dir)), name="user-data")

    if list(static_dir.glob("*.html")):
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        app.mount("/assets", StaticFiles(directory=str(__app_root__ / "assets")), name="assets")

        @app.get("/")
        async def index():
            return FileResponse(str(static_dir / "index.html"))

    return app


async def _cmd_serve(args: list[str]) -> None:
    import argparse
    import webbrowser

    parser = argparse.ArgumentParser(prog="router serve")
    parser.add_argument("--host", default=cfg.host)
    parser.add_argument("--port", type=int, default=cfg.port)
    parser.add_argument("--no-browser", action="store_true")
    opts = parser.parse_args(args)

    import uvicorn

    # 启动校验
    warnings = cfg.validate()
    if warnings:
        print("  配置警告:")
        for w in warnings:
            print(f"    ! {w}")
        print()

    app = create_app()

    print(f"\n  服务启动: http://{opts.host}:{opts.port}")
    print(f"  后端: {', '.join(_backends.configured_keys) or '无'}\n")

    if not opts.no_browser:
        webbrowser.open(f"http://{opts.host}:{opts.port}")

    config = uvicorn.Config(app, host=opts.host, port=opts.port, log_level="warning")
    await uvicorn.Server(config).serve()


async def _cmd_video(args: list[str]) -> None:
    """CLI 视频生成。"""
    import argparse

    parser = argparse.ArgumentParser(prog="router video")
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--reference-image", "-r", action="append", default=None,
                        help="参考图路径（可多次指定）")
    parser.add_argument("--negative-prompt", "-np", default=None,
                        help="反向提示词（不想要的内容）")
    parser.add_argument("--mode", default=None,
                        choices=["text", "keyframe", "reference"],
                        help="生成模式: text=文生视频, keyframe=首尾帧, reference=多参考图")
    parser.add_argument("--seconds", default=None,
                        help="视频时长（4-12 秒，默认 5）")
    parser.add_argument("--aspect-ratio", default=None,
                        help="画面比例（如 16:9 / 9:16 / 1:1 / 4:3 / 3:4 / 21:9）")
    parser.add_argument("--seed", type=int, default=None,
                        help="随机种子（可复现结果）")
    opts = parser.parse_args(args)

    prompt = " ".join(opts.prompt) or input("请输入视频生成提示词: ")
    output_dir = Path(opts.output) if opts.output else Path.cwd() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 参考图 → Base64 编码
    reference_images = None
    if opts.reference_image:
        reference_images = [_encode_image_to_base64(p) for p in opts.reference_image]
        print(f"  参考图: {len(reference_images)} 张")

    if opts.negative_prompt:
        print(f"  反向提示词: {opts.negative_prompt}")
    if opts.mode:
        print(f"  模式: {opts.mode}")
    if opts.seconds:
        print(f"  时长: {opts.seconds} 秒")
    if opts.aspect_ratio:
        print(f"  画面比例: {opts.aspect_ratio}")
    if opts.seed is not None:
        print(f"  种子: {opts.seed}")

    print(f"\n  提交视频生成任务...")
    router = SmartRouter()
    try:
        result = await router.generate_video(
            prompt,
            negative_prompt=opts.negative_prompt,
            reference_images=reference_images,
            mode=opts.mode,
            seconds=opts.seconds,
            aspect_ratio=opts.aspect_ratio,
            seed=opts.seed,
        )
    except AdapterError as e:
        print(f"\n  错误: {e}\n")
        sys.exit(1)

    task_id = result.get("id") or result.get("task_id", "")
    status = result.get("status", "unknown")
    print(f"  任务 ID: {task_id}")
    print(f"  状态: {status}")
    print(f"  原始响应: {result}")
    print()

    # 如果是异步任务，开始轮询
    if status in ("queued", "processing", "submitted", "pending"):
        print("  等待视频生成完成...")
        agnes = _backends.get("agnes")
        import asyncio as _asyncio
        while True:
            await _asyncio.sleep(5)
            try:
                s = await agnes.get_video_status(task_id) if isinstance(agnes, AgnesAdapter) else {}
            except Exception:
                continue
            st = s.get("status", "")
            print(f"    状态: {st}")
            if st in ("completed", "done", "ready", "succeeded"):
                result = s
                break
            elif st in ("failed", "error", "cancelled"):
                print(f"\n  视频生成失败: {s}\n")
                sys.exit(1)

    # 尝试提取视频 URL
    video_url = (
        result.get("video_url")
        or result.get("url")
        or result.get("output", {}).get("url")
        or ""
    )
    if video_url:
        ts = int(time.time() * 1000)
        filepath = output_dir / f"agnes_video_{ts}.mp4"
        print(f"  下载视频中... {video_url}")
        import httpx
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            r = await client.get(video_url)
            r.raise_for_status()
            filepath.write_bytes(r.content)
        print(f"  已保存: {filepath}")
    else:
        print(f"  响应: {result}")

    print()


# ============================================================
# Main
# ============================================================

async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "chat":
        await _cmd_chat(rest)
    elif cmd == "image":
        await _cmd_image(rest)
    elif cmd == "video":
        await _cmd_video(rest)
    elif cmd == "serve":
        await _cmd_serve(rest)
    else:
        print(f"未知命令: {cmd}\n可用: chat | image | video | serve")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
