# Fate/Grand Order: Moon Cell Collector (LLM Edition)

[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/python-3.9+-yellow.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

这是一个结合了 **Fate/Grand Order** 世界观与 **LLM (大语言模型)** 的同人项目。它不仅包含了一个全语音、全动画的英灵召唤模拟器，还内置了一个由 AI 驱动的圣杯战争文字冒险游戏引擎。

## ✨ 主要功能

### 1. 🌌 英灵召唤系统
*   **真实模拟**：还原 FGO 经典的召唤动画与特效。
*   **全语音收录**：包含数百位英灵的召唤语音与立绘。
*   **卡池管理**：基于本地 `chara/` 目录的数据动态生成卡池。

### 2. ⚔️ 圣杯战争模拟 (AI Game)
*   **无限剧情**：利用 LLM 实时生成剧情，每次游戏的体验都独一无二。
*   **三阶段流水线**：
    *   **感知**：AI 分析当前战局与环境。
    *   **决策**：基于英灵性格（如吉尔伽美什的傲慢、阿尔托莉雅的骑士道）决定行动。
    *   **行动**：生成具体的战斗描述与结果。
*   **多角色互动**：支持 Master 与 Servant 之间的对话互动。

## 🚀 快速开始

### 方式一：Docker 一键启动 (推荐)

无需配置 Python 环境，只需安装 [Docker Desktop](https://www.docker.com/products/docker-desktop)。

1.  **克隆项目**
    ```bash
    git clone https://github.com/your-username/moon-cell-collector.git
    cd moon-cell-collector
    ```

2.  **配置 API Key**
    *   复制 `.env.example` 为 `.env`。
    *   编辑 `.env` 文件，填入你的 LLM API 地址和 Key（支持 OpenAI 兼容格式与 Gemini 格式）。
    ```ini
    # 切换请求格式：openai | gemini
    LLM_API_FORMAT=openai

    # OpenAI 兼容格式
    LLM_API_URL=https://api.openai.com/v1/chat/completions
    LLM_API_KEY=your-sk-key
    LLM_MODEL_ID=gpt-4

    # Gemini 格式示例（使用同一套变量）
    # LLM_API_FORMAT=gemini
    # LLM_API_URL=https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}
    # LLM_API_KEY=your-gemini-key
    # LLM_MODEL_ID=gemini-2.0-flash
    ```

3.  **启动服务**
    *   **Windows**: 双击运行 `start_docker.bat`。
    *   **Linux/Mac**: 运行 `docker-compose up -d --build`。

4.  **访问游戏**
    *   🔮 **召唤模拟器**: [http://localhost:5000/summon.html](http://localhost:5000/summon.html)
    *   🎮 **文字冒险**: [http://localhost:5000/game.html](http://localhost:5000/game.html)

### 方式二：本地 Python 运行

如果你想修改代码或进行调试：

1.  **环境准备**
    *   Python 3.9+
    *   安装依赖：
        ```bash
        pip install -r requirements.txt
        ```

2.  **配置环境变量**
    *   同上，确保项目根目录下有配置好的 `.env` 文件。

3.  **运行后端**
    ```bash
    python summon_api.py
    ```

## 📂 目录结构

```text
moon-cell-collector/
├── chara/                  # 英灵数据资源 (图片/语音/JSON)
├── class_image/            # 职阶图标
├── game_engine/            # 游戏核心逻辑 (State, Loop, Models)
├── summon_api.py           # Flask 后端入口
├── summon.html             # 召唤界面前端
├── game.html               # 游戏界面前端
├── Dockerfile              # Docker 构建文件
└── ...
```

## 🛠️ 自定义与扩展

*   **添加英灵**：在 `chara/` 目录下新建文件夹，放入 `images/` (立绘) 和 `voices.json` 即可被系统自动识别。
*   **修改提示词**：游戏的核心 Prompt 位于 `game_engine/` 目录下的 Python 脚本中，可根据需要调整 AI 的扮演风格。

## ⚠️ 注意事项

*   **API 消耗**：游戏剧情生成需要频繁调用 LLM API，请注意 Token 消耗。
*   **资源版权**：本项目使用的图片和语音资源版权归 **TYPE-MOON / FGO Project** 所有，仅供学习交流使用，请勿用于商业用途。

## 📄 License

MIT License
