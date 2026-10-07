# FloatShot

Windows 截图贴图工具：按全局热键框选屏幕区域，截图以置顶悬浮窗留在桌面，可拖动、缩放、标注，并可调用视觉大模型识别图片。

![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)

## 功能

- 全局热键截屏（默认 `Ctrl+Alt+Q`，可在设置里修改）
- 先抓屏再框选，遮罩不会进图；支持多显示器（含负坐标）
- 悬浮窗：置顶、无边框、手绘阴影/描边/角点、悬停淡入关闭按钮
- 八方向缩放，按住 `Shift` 等比缩放
- 标注工具栏：矩形、椭圆、箭头、画笔、文字、马赛克、序号、高亮
  - 文字可拖动 / 缩放 / 旋转
  - 调色盘改颜色，粗细按钮改描边宽度，支持撤销 / 重做
- AI 识别横条：在截图下方输入问题或点预制提示词，调用视觉模型识别图片，答案在横条下方展开
- 截图后自动复制到剪贴板（可选）
- 托盘常驻：打开主界面 / 退出
- Qt 设置窗口（标签页），所有可调项写入 `config.json`
- 单文件 exe 打包（PyInstaller）

## 系统要求

- Windows 10 / 11（深度依赖 Win32 API，仅 Windows）
- 运行时仅依赖 **PySide6**

## 下载

从 [Releases](https://github.com/larry3033/floatshot/releases) 下载 `FloatShot.exe`（单文件，无需安装 Python）。首次运行会在 exe 同目录生成 `config.json`。

## 使用

1. 启动后进入设置窗口；关闭它只是隐藏，程序仍在托盘。
2. 按热键（默认 `Ctrl+Alt+Q`）或托盘「立即截屏」→ 框选区域。
3. 截图变为悬浮窗；单击截图弹出标注工具栏，右键是 复制 / 另存为 / 关闭。
4. 点工具栏「AI」→ 截图下方出现单行横条，输入问题回车或点预制提示词识别图片，结果在横条下方展开。

> 截屏时设置窗口会自动隐藏，避免被拍进图里。

## 从源码运行 / 开发

```powershell
pip install -r requirements.txt
python main.py
```

运行测试：

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

打包单文件 exe：

```powershell
pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File build.ps1
```

产物为 `dist\FloatShot.exe`。

## AI 识别配置

在设置窗口的「AI 识别」标签页修改，或直接编辑 `config.json` 的 `ai` 节：

```json
"ai": {
  "format": "claude",
  "base_url": "https://api.deepseek.com/anthropic",
  "model": "deepseek-flash",
  "api_key": "",
  "api_key_env": "FLOATSHOT_API_KEY",
  "timeout_s": 60,
  "max_tokens": 1024,
  "system_prompt": "你是一个图片理解助手……",
  "presets": ["描述这张图片的内容", "提取图中的所有文字"]
}
```

- `format = "openai"` → `POST {base_url}/chat/completions`，图片用 `image_url` 的 data URI。
- `format = "claude"` → `POST {base_url}/v1/messages`，图片用 base64 `source` 块。
- 响应两种方言都能解析（推理模型的 `thinking` 块会被跳过）。
- 提示词规则：输入框有内容则发送输入内容，为空则发送 `system_prompt`。

**API Key 安全**：优先使用 `ai.api_key`，为空则读取 `ai.api_key_env` 指定的环境变量。`config.json` 已在 `.gitignore` 中——请勿把 key 提交到仓库，也不要随 exe 分发。

## 目录结构

```
main.py                      入口
floatshot/
  __init__.py                DPI 环境变量与感知声明（必须在 Qt import 之前）
  dpi.py metrics.py geometry.py hotkey_spec.py config.py annotations.py settings.py
                            纯函数层（单元测试的落点）
  capture.py overlay.py float_window.py hotkey.py tray.py
  toolbar.py annotation_paint.py ai_client.py ai_bar.py
  settings_window.py app.py
tests/                       单元测试
build.ps1                    PyInstaller 打包脚本
```

## 已知限制

- 仅支持 Windows。
- 全局热键可能被其他程序占用，换一个即可。
- 多显示器 DPI 不一致时，界面元素按系统 DPI 缩放（首版限制）。
- 打包后的 exe 建议在 125% / 150% 缩放的屏幕上用「诊断信息」核对 DPI 探测。

## 许可证

[GNU Affero General Public License v3.0 or later](LICENSE)（AGPL-3.0-or-later）。
