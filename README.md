# 不绘来世

> 一个智能 LLM 路由代理，根据任务类型自动选择合适的模型，并支持文本对话、图片生成、视频生成、联网搜索等功能。

**Agnes** 负责轻量、多模态任务，**DeepSeek** 负责复杂推理与联网搜索。

---

## ✨ 核心功能

- 🤖 **智能模型路由** — 根据任务类型自动选择模型
- 💬 **AI 对话** — 支持 Agnes / DeepSeek
- 🖼 **对话上传图片** — 选择、拖拽或粘贴图片，预览条确认后随消息发送，自动路由到 Agnes 视觉模型（预览条浮出于输入区上方，不撑高底栏）
- 🎨 **图片生成** — 支持多尺寸、多比例、参考图
- 🎬 **视频生成** — 支持图生视频、关键帧及异步生成
- 🖼 **画布模式** — 节点式几何画布：参考图 / 图片生成 / 视频生成三类节点，连线即数据流，画布上直接生图生视频
- 🌐 **联网搜索** — 获取实时信息
- 🧠 **深度创作** — 搜索资料后生成内容
- 📖 **内置 API 文档** — 直接查看项目 API
- 🎨 **主题与背景** — 支持自定义主题、壁纸、透明度
- 🖥️ **桌面版** — 可通过 PyInstaller 打包为 Windows `.exe`
- 🔌 **OpenAI 兼容 API** — 可作为本地 AI 服务供其他程序调用

---

## 🧠 路由策略

系统根据任务类型自动选择后端：

| 任务         | 后端               |
| ---------- | ---------------- |
| 图片 / 文件识别  | Agnes            |
| 图片 / 视频生成  | Agnes            |
| 翻译、摘要、简单问答 | Agnes            |
| 代码、数学、复杂推理 | DeepSeek         |
| 联网搜索       | DeepSeek         |
| 深度创作       | DeepSeek → Agnes |

也支持在 Web 界面或 CLI 中手动指定模型。

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- Windows / macOS / Linux
- Agnes / DeepSeek API Key

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

复制 `.env.example` 为 `.env`，再填入你自己的密钥：

```bash
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```

编辑 `.env`，至少填写两项必填 KEY：

```env
AGNES_API_KEY=your_agnes_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
```

> 带默认值的项（如 `AGNES_BASE_URL`、`ROUTER_PORT`）可留空，详见 `.env.example` 内注释。

### 4. 启动

```bash
python launcher.py
```

启动后访问：

```text
http://127.0.0.1:8800
```

---

## 💻 使用方式

### Web 界面

```bash
python launcher.py
```

提供：

- 智能对话（支持上传/拖拽/粘贴图片，图片自动路由到 Agnes 视觉模型）
- 图片生成
- 视频生成
- 画布模式（节点式几何画布：参考图 / 图片生成 / 视频生成，连线 + 画布内直接生成）
- API 文档
- 设置
- 关于

### CLI

```bash
# 自动路由
python router.py chat "用 Python 写一个快速排序"

# 指定 DeepSeek
python router.py chat --backend deepseek "分析这段代码"

# 图片生成
python router.py image "一只穿宇航服的猫"

# 视频生成
python router.py video "海浪拍打沙滩"
```

### API 服务

```bash
python router.py serve --no-browser
```

提供 OpenAI 兼容接口：

```text
POST /v1/chat/completions
POST /v1/images/generations
POST /v1/video/generations
GET  /v1/video/status/{task_id}
GET  /health
GET  /v1/backends
```

### 画布模式 🖼（几何画布）

侧边栏"画布"入口进入全屏**节点式几何画布**，支持三种节点（📷 参考图 / 🎨 图片生成 / 🎬 视频生成），连线即数据流，**在画布上直接生图、生视频**。特性：

- **手动连线**（ComfyUI 风格）+ **节点内嵌参数面板**，双击或 ⚙ 展开、点「▶ 生成」即出结果，结果直接显示在节点内并可继续喂给下游
- **结果可保存 / 全屏预览** — 生成后一键存到 `output/`，缩略图 ⛶ 放大（图片滚轮缩放、视频直接播放）
- **画布操作** — 拖文件快速加参考图、右下角小地图、⊡ 适应画布、Ctrl+滚轮缩放、右键菜单管理节点
- **视频三段综合进度条**（排队→生成→下载）+ 实时轮询任务状态


---


## 🖥️ 桌面版

项目支持使用 PyInstaller 打包：

```bash
pip install pywebview pyinstaller pillow
python build.py
```

生成：

```text
dist/不绘来世.exe
```

桌面版具有：

- 原生窗口
- 应用图标
- 本地运行
- 图片 / 视频输出
- 设置持久化

---

## 📁 项目结构

```text
agnes-router/
├── launcher.py          # Web 版启动入口
├── desktop.py           # 桌面版入口
├── router.py            # 核心路由与 API 服务
├── classifier.py        # 任务分类
├── adapters.py          # API 适配层
├── config.py            # 配置管理
├── build.py             # 打包脚本
├── generate_icon.py     # 图标生成
├── static/
│   └── index.html       # Web 前端
├── assets/              # 图片、视频、字体等资源
├── requirements.txt     # Python 依赖
├── .env.example         # 环境变量模板
└── README.md
```

---

## 🔌 API

### Chat

```http
POST /v1/chat/completions
```

支持自动路由、联网搜索和深度创作。

### Image

```http
POST /v1/images/generations
```

支持模型、尺寸、比例、参考图等参数。

### Video

```http
POST /v1/video/generations
GET /v1/video/status/{task_id}
```

支持异步视频生成与任务状态查询。

### 其他

```http
GET  /health
GET  /v1/backends
GET  /api/config
POST /api/config
GET  /api/settings
POST /api/settings
```

##
