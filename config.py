"""
统一配置管理 —— 加载 .env，校验必填项，提供全局配置单例。

用法:
    from config import cfg
    print(cfg.agnes.api_key)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """配置错误"""
    pass


# ============================================================
# 单个后端配置
# ============================================================

@dataclass
class BackendConfig:
    """单个后端的配置。"""
    name: str                          # 显示名称，如 "Agnes"
    key: str                           # 内部标识，如 "agnes"
    api_key: str = ""
    base_url: str = ""
    model: str = ""                    # 文本模型
    image_model: str = ""              # 图片生成模型（默认/兜底）
    image_models: list[str] = field(default_factory=list)  # 图片模型列表
    video_model: str = ""              # 视频生成模型（默认/兜底）
    video_models: list[str] = field(default_factory=list)  # 视频模型列表
    proxy: str | None = None
    enabled: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)


# ============================================================
# 分类器配置
# ============================================================

@dataclass
class ClassifierConfig:
    """任务分类器的关键词配置，可在 .env 中覆盖。"""
    # 复杂推理关键词 (逗号分隔)
    complex_keywords: str = ""
    # 简单任务关键词
    simple_keywords: str = ""
    # 复杂度阈值（达到此分数 → DeepSeek）
    complexity_threshold: int = 1
    # 短消息兜底阈值（字符数）
    short_message_limit: int = 200


# ============================================================
# 全局配置
# ============================================================

@dataclass
class AppConfig:
    """全局应用配置。"""
    agnes: BackendConfig = field(default_factory=lambda: BackendConfig(
        name="Agnes",
        key="agnes",
        api_key=os.getenv("AGNES_API_KEY", ""),
        base_url=os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1"),
        model=os.getenv("AGNES_TEXT_MODEL", "agnes-2.5-flash"),
        image_model=os.getenv("AGNES_IMAGE_MODEL", "agnes-image-2.1-flash"),
        image_models=[m.strip() for m in os.getenv("AGNES_IMAGE_MODELS", "").split(",") if m.strip()] or ["agnes-image-2.1-flash"],
        video_model=os.getenv("AGNES_VIDEO_MODEL", "agnes-video-v2.0"),
        video_models=[m.strip() for m in os.getenv("AGNES_VIDEO_MODELS", "").split(",") if m.strip()] or ["agnes-video-v2.0"],
        proxy=os.getenv("AGNES_PROXY", None),
    ))
    deepseek: BackendConfig = field(default_factory=lambda: BackendConfig(
        name="DeepSeek",
        key="deepseek",
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        proxy=os.getenv("DEEPSEEK_PROXY", None),
    ))
    classifier: ClassifierConfig = field(default_factory=lambda: ClassifierConfig(
        complex_keywords=os.getenv("CLASSIFIER_COMPLEX_KEYWORDS", ""),
        simple_keywords=os.getenv("CLASSIFIER_SIMPLE_KEYWORDS", ""),
        complexity_threshold=int(os.getenv("CLASSIFIER_COMPLEXITY_THRESHOLD", "1")),
        short_message_limit=int(os.getenv("CLASSIFIER_SHORT_LIMIT", "200")),
    ))

    host: str = os.getenv("ROUTER_HOST", "127.0.0.1")
    port: int = int(os.getenv("ROUTER_PORT", "8800"))

    @property
    def backends(self) -> list[BackendConfig]:
        """返回所有已启用的后端。"""
        return [b for b in [self.agnes, self.deepseek] if b.enabled]

    def validate(self) -> list[str]:
        """校验配置，返回警告列表。"""
        warnings: list[str] = []
        if not self.deepseek.is_configured:
            warnings.append("DeepSeek API Key 未配置，复杂推理将不可用")
        if not self.agnes.is_configured:
            warnings.append("Agnes API Key 未配置，多模态和图片生成将不可用")
        return warnings


# ============================================================
# 初始化
# ============================================================

def _init_config() -> AppConfig:
    """加载 .env 并创建全局配置。"""
    from dotenv import load_dotenv

    # 尝试多个路径加载 .env
    env_paths = [
        Path(os.environ.get("APP_ROOT", "")) / ".env",
        Path.cwd() / ".env",
        Path(__file__).parent / ".env",
        Path(__file__).parent.parent / ".env",
    ]
    for p in env_paths:
        if p.exists():
            load_dotenv(p)
            break

    cfg = AppConfig()
    return cfg


# 全局单例
cfg = _init_config()
