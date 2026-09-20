"""
任务分类器 —— 判断请求应该路由到哪个后端。

规则按优先级从高到低排列，命中即停止：
  1. 消息包含图片/多模态输入     → 多模态后端
  2. 请求图片/视频生成           → 生成后端
  3. 复杂度评分 >= 阈值          → 推理后端
  4. 匹配简单任务关键词          → 简单后端
  5. 消息 < 短消息阈值           → 简单后端（兜底）
  6. 其余                       → 推理后端（兜底）

可通过 .env 自定义关键词：
  CLASSIFIER_COMPLEX_KEYWORDS=分析,代码,算法
  CLASSIFIER_SIMPLE_KEYWORDS=翻译,你好
  CLASSIFIER_COMPLEXITY_THRESHOLD=2
  CLASSIFIER_SHORT_LIMIT=200
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from config import cfg


# -----------------------------------------------------------
# 默认关键词
# -----------------------------------------------------------

DEFAULT_COMPLEX_KEYWORDS = [
    "分析", "推理", "证明", "推导", "论证",
    "设计", "代码", "编程", "debug", "调试", "算法", "algorithm",
    "架构", "系统设计", "设计方案", "architecture",
    "数学", "公式", "方程", "计算", "math",
    "逻辑", "悖论",
    "逐步", "step by step", "一步一步",
    "审查", "审计", "review", "refactor", "重构", "优化",
    "时间复杂度", "空间复杂度",
    "复杂", "深入", "详细分析",
    # 编程语言 & 代码信号
    "python", "java", "javascript", "c++", "golang", "rust", "typescript",
    "排序", "查找", "搜索算法", "递归", "动态规划",
    "实现", "编写", "函数", "类", "接口",
    "bug", "修复", "错误", "异常",
    "正则", "sql", "数据库", "查询",
    "闭包", "原型链", "异步", "线程", "进程",
    # 联网搜索 & 实时信息需求 → DeepSeek
    "搜索", "查询", "查一下", "search",
    "最新", "最近", "今天", "现在",
    "新闻", "资讯", "热点", "事件",
    "联网", "上网",
    "科普", "百科", "wiki",
    "资料", "官方文档",
]

DEFAULT_SIMPLE_KEYWORDS = [
    "翻译", "translate", "翻译成",
    "总结", "摘要", "概括", "summarize",
    "解释", "是什么", "定义",
    "你好", "谢谢", "再见",
    "写邮件", "写文案", "写通稿",
]

MULTIMODAL_KEYWORDS = [
    "图片", "图像", "照片", "截图", "看图", "图中", "这张图",
    "视频", "影片", "画面", "帧",
    "生成图片", "生成图像", "画一张", "画个", "生成一张",
    "生成视频", "做视频", "制作视频",
    "识别图片", "识别图像", "图片识别", "OCR",
    "生图", "文生图", "图生图", "图生视频",
    "image", "picture", "photo", "screenshot",
    "video", "img", "jpg", "png",
]

# -----------------------------------------------------------
# 分类结果
# -----------------------------------------------------------

@dataclass
class ClassifyResult:
    backend: str          # 后端 key，如 "agnes" | "deepseek"
    reason: str           # 决策原因
    model_override: str | None = None  # 可选：指定具体模型


# -----------------------------------------------------------
# 分类器
# -----------------------------------------------------------

class TaskClassifier:
    """
    可配置的任务分类器。

    可通过 .env 或构造函数参数覆盖关键词：
      Classifier(complex_keywords=["分析","代码"], simple_keywords=["翻译"])
    """

    def __init__(
        self,
        complex_keywords: list[str] | None = None,
        simple_keywords: list[str] | None = None,
        complexity_threshold: int | None = None,
        short_message_limit: int | None = None,
        # 后端映射
        multimodal_backend: str = "agnes",
        generation_backend: str = "agnes",
        simple_backend: str = "agnes",
        complex_backend: str = "deepseek",
    ):
        # 支持 .env 覆盖（逗号分隔字符串 → 列表合并）
        env_complex = _parse_env_keywords(cfg.classifier.complex_keywords)
        env_simple = _parse_env_keywords(cfg.classifier.simple_keywords)

        self.complex_keywords = complex_keywords or DEFAULT_COMPLEX_KEYWORDS
        if env_complex:
            self.complex_keywords = env_complex
        self.simple_keywords = simple_keywords or DEFAULT_SIMPLE_KEYWORDS
        if env_simple:
            self.simple_keywords = env_simple

        self.complexity_threshold = complexity_threshold or cfg.classifier.complexity_threshold
        self.short_message_limit = short_message_limit or cfg.classifier.short_message_limit

        # 后端映射（可自定义）
        self.multimodal_backend = multimodal_backend
        self.generation_backend = generation_backend
        self.simple_backend = simple_backend
        self.complex_backend = complex_backend

    # ---- 分类 ----

    def classify(self, messages: list[dict[str, Any]]) -> ClassifyResult:
        """分析消息列表，返回路由决策。"""
        full_text = _extract_text(messages)
        has_images = _has_image_content(messages)

        # 规则 1：多模态 → 多模态后端
        if has_images:
            return ClassifyResult(
                backend=self.multimodal_backend,
                reason="包含图片/多模态输入 → 多模态后端",
            )

        # 规则 2：请求生成 → 生成后端
        if _wants_generation(full_text):
            return ClassifyResult(
                backend=self.generation_backend,
                reason="请求图片/视频生成 → 生成后端",
            )

        # 规则 3：复杂推理 → 推理后端
        score = _complexity_score(full_text, self.complex_keywords)
        if score >= self.complexity_threshold:
            return ClassifyResult(
                backend=self.complex_backend,
                reason=f"复杂推理 (复杂度评分: {score}) → 推理后端",
            )

        # 规则 4：简单任务 → 简单后端
        if _is_simple_task(full_text, self.simple_keywords):
            return ClassifyResult(
                backend=self.simple_backend,
                reason="简单任务 → 简单后端",
            )

        # 规则 5：短消息兜底
        if len(full_text) < self.short_message_limit:
            return ClassifyResult(
                backend=self.simple_backend,
                reason=f"短消息 ({len(full_text)} 字符) → 简单后端",
            )

        # 规则 6：长消息兜底
        return ClassifyResult(
            backend=self.complex_backend,
            reason=f"长消息 ({len(full_text)} 字符) → 推理后端",
        )


# ============================================================
# 辅助函数
# ============================================================

def _parse_env_keywords(raw: str) -> list[str]:
    """解析 .env 中的逗号分隔关键词。"""
    if not raw or not raw.strip():
        return []
    return [kw.strip() for kw in raw.split(",") if kw.strip()]


def _extract_text(messages: list[dict[str, Any]]) -> str:
    """从消息列表中提取纯文本。"""
    texts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(part.get("text", ""))
    return "\n".join(texts)


def _has_image_content(messages: list[dict[str, Any]]) -> bool:
    """检查消息中是否包含图片。"""
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") in ("image_url", "image", "vision"):
                        return True
                    if "image_url" in part:
                        return True
                    if "url" in part and any(
                        ext in str(part.get("url", ""))
                        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]
                    ):
                        return True
    return False


def _wants_generation(text: str) -> bool:
    """检查是否请求生成（图片或视频）。"""
    gen_patterns = [
        r"生成.*[图图片视频画面]",
        r"(画|做|创建|制作).*[图图片视频]",
        r"(generate|create|make|draw)\s+(an?\s+)?(image|picture|video|photo)",
        r"文生[图视]|图生[图视]",
        r"帮我.*[画做].*[图图图视]",
    ]
    for pat in gen_patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def _wants_video(text: str) -> bool:
    """检查是否请求视频生成。"""
    video_patterns = [r"视频", r"video", r"影片", r"动画"]
    return any(re.search(p, text, re.IGNORECASE) for p in video_patterns)


def _complexity_score(text: str, keywords: list[str]) -> int:
    """对文本复杂度进行评分。"""
    score = 0
    lower = text.lower()

    # 精确匹配模式（高权重）
    high_weight = [
        (r"\b(代码|编程|code|program|debug|算法|algorithm)\b", 3),
        (r"\b(架构|系统设计|设计方案|architecture)\b", 3),
        (r"\b(时间复杂度|空间复杂度|复杂度分析)\b", 2),
        (r"\b(数学|公式|方程|math|equation)\b", 2),
    ]
    for pat, weight in high_weight:
        if re.search(pat, lower):
            score += weight

    # 宽松匹配（低权重）
    for kw in keywords:
        if kw.lower() in lower:
            score += 1

    # 文本长度加分
    if len(text) > 800:
        score += 1
    if len(text) > 2000:
        score += 1

    return score


def _is_simple_task(text: str, keywords: list[str]) -> bool:
    """判断是否为简单任务。"""
    lower = text.lower()
    for kw in keywords:
        if kw.lower() in lower:
            return True
    if len(text.strip()) < 5:
        return True
    return False


# ============================================================
# 兼容旧接口
# ============================================================

_default_classifier = TaskClassifier()


def classify(messages: list[dict[str, Any]]) -> ClassifyResult:
    """兼容旧代码的模块级函数。"""
    return _default_classifier.classify(messages)
