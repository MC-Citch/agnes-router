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

侧边栏"画布"入口进入全屏**节点式几何画布**，支持三种节点（📷 参考图 / 🎨 图片生成 / 🎬 视频生成），连线即数据流，**在画布上直接生图、生视频**，无需回到视频页：

- **三种节点**
  - 📷 参考图 — 输入节点，自带图片，向下游输出参考数据
  - 🎨 图片生成 — 内嵌提示词 + 清晰度（1K–4K）/ 比例 / 数量 / 反向提示词，节点内直接显示生成图
  - 🎬 视频生成 — 内嵌提示词 + 画幅 / 时长（4/5/8/12s）/ 模式 / 种子 / 反向提示词，节点内直接播放生成视频
- **节点展开窗口** — 双击节点或点 ⚙，右侧滑出 244px 紧凑参数面板（高度自适应内容、不拖满整屏），按节点类型渲染对应表单，点「▶ 生成」即出结果
- **手动连线**（ComfyUI 风格）— 从输出端口拖到输入端口建立数据流；video 节点前两根连线 = 首帧 / 尾帧
- **右键菜单** — 画布空白处：添加参考图 / 生成图片 / 生成视频 / 适应画布 / 重置视图；节点上：展开参数 / 生成 / 重新选图 / 复制 / 删除
- **画布内生成** — 图片结果节点内显示缩略图，视频结果节点内 `<video>` 直接播放，可继续连线喂给下游
- **节点随画幅自适应** — 生成节点结果区高度按所选画幅比例自动伸缩（16:9 矮、9:16 高、21:9 最矮），`object-fit:contain` 完整不变形；**参考图节点**按真实图片高宽比自适应高度（96–360px 内），`object-fit:contain` 不变形；连线端口 / 小地图 / 适应画布均跟随节点实际尺寸
- **添加节点不重置画布** — 新建/选图添加节点时只在当前视口位置插入，不自动缩放平移；工具栏 ⊡ 与右键「适应画布」仍可随时手动居中全部节点
- **结果可保存** — 图片 / 视频节点生成完成后，展开面板内出现「💾 保存图片 / 保存视频」按钮，一键存到本地 `output/` 目录并提示保存路径
- **节点全屏预览** — 生成节点结果缩略图右上角（hover 显示）有 ⛶ 按钮：图片走黑底放大 overlay（滚轮缩放），视频走黑底居中 overlay 直接播放（带 controls，点遮罩 / ESC 关闭）
- **连线渲染** — SVG 贝塞尔曲线铺满世界坐标，不随 pan/zoom 偏移出错；hover 连线（加宽透明命中线）后点击线本身即可删线，无多余中点圆点
- **视频状态轮询** — 画布内生成视频时轮询任务状态，字段提取穿透 Agnes 的 `{code, data}` 包装结构，完成即节点内播放，不会卡"生成中"
- **三段综合进度条** — 视频页生成视频的进度条统一表达「① 排队(0–10%) → ② 生成(10–80%) → ③ 下载(80–100%)」综合进展：生成段跟随 Agnes 真实渲染进度，完成后进入下载段，用流式 fetch 按 `已接收字节/总字节` 推进视频载入前端的进度（有 `Content-Length` 时精确，否则对数平滑 + 时间兜底）；分段刻度线 + 三段小标签标示当前段，文案显示「段内 % · 综合 %」，生成速度与下载速度合并呈现，不再只反映服务端渲染
- **纯画布** — 无底部输入条，提示词与所有参数均内嵌在各节点展开面板中
- **缩放** — Ctrl+滚轮 / 工具栏 +−按钮，以鼠标位置为中心缩放，范围 25%–300%
- **平移** — 普通滚轮 / 空格+拖拽 / 中键拖拽，带网格背景同步移动
- **拖拽添加** — 直接拖文件到画布任意位置，松开即在该处放置参考图节点（支持多文件）
- **小地图** — 右下角实时显示全貌，按节点类型着色，蓝色框标示当前视口
- **适应画布** — 工具栏 ⊡ 按钮自动缩放平移，让所有节点居中
- **Delete / Esc** — Delete 删选中节点；Esc 关闭右键菜单与参数面板

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
