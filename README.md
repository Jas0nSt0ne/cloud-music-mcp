<p align="center">
  <img src="logo.png" width="128" alt="NetEase Cloud Music MCP Logo">
</p>

# NetEase Cloud Music MCP（网易云音乐 MCP 服务器）

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) ![Pull Requests Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen)

> 基于 [网易云音乐开发平台](https://developer.music.163.com/st/developer/) 标准 API 实现

**🎵 为您的 AI Agent 插上音乐的翅膀**

这是一个基于 **网易云音乐 官方API** 的本地MCP服务器。可以让用户通过 Claude Code, OpenCode 等 AI Agent以**原生 API** 的方式点歌!

## 📢 Update

- **2026-08-30** 🔒 v0.2.1 安全修复 — 撤销历史泄露的登录态，从本地及 GitHub 分支/标签历史中清除 Cookie、Session 和二维码文件，并增加通用敏感文件忽略规则；项目对外名称统一为 `netease-cloud-music-mcp`。
- **2026-08-18** 🖥️ v0.2.0 重构 Windows 播放控制 — 识别 Codex 隔离桌面，新增真实窗口与播放状态双重校验、每日推荐按位置直接播放、搜索并播放以及结构化错误码。已知限制：在 Codex 隔离环境中，客户端完全退出后的自动启动暂不可用。
- **2026-06-29** 🎉 新增歌单管理 — AI 现在可以帮你创建歌单并批量添加歌曲，一句话完成「搜歌 → 建单 → 加歌」全流程。
- **2026-06-29** 🔎 新增资料查询 — 支持查询歌单详情、专辑信息、歌手信息以及你的收藏列表。
- **2026-06-16** 🔧 修复安装问题 — 替换已失效的 PyPI pyncm 为自维护 fork，补齐 build-system，并清除误提交的登录态等敏感文件。

## ✨ 功能特性

- **🤖 让 AI Agent 为你播放音乐**：通过自然语言指令控制音乐播放。只需说“给我放首热血的歌”，Agent 就会为你搞定一切。
- **🔓 扫码登录**：必须使用已登录的手机端网易云音乐 App 内置“扫一扫”完成授权；微信、系统相机或普通浏览器扫码只能打开链接，无法完成登录。登录状态（Cookies）仅保存在本地，保护您的隐私。
- **🧠 个性化推荐**：完美接入您的**每日推荐**和**歌单**。Agent 会根据您的听歌品味来播放音乐。
- **🔍 搜歌功能**：支持按关键词搜索歌曲、歌手或专辑，并直接播放。
- **📝 歌单管理**：不只是放歌，还能帮你创建歌单、批量加歌。说一句"建个某个主题的歌单"，AI 就会自动搜歌、建单、加歌一气呵成。
- **📷 BGM 清单导入**：发送视频片尾的歌曲清单截图，即可逐首匹配、去重并导入当天歌单；默认名称为 `YYYYMMDD歌单`，也可使用 `YYYYMMDD自定义名称`。高置信歌曲自动加入，歧义版本会先请你确认。
- **🎛️ 官方客户端联动**：在 Windows 上控制网易云音乐官方客户端，并在成功前同时校验曲目、播放状态和真实输入桌面上的主窗口。MCP 不下载或解码音频。
- **🧭 隔离桌面感知**：能区分 `CodexSandboxDesktop` 与 Windows `Default` 桌面，不再出现“能听见但看不见客户端”或假成功。
- **⚡ 直接动作工具**：支持按位置播放每日推荐，以及搜索后直接播放指定结果，减少 Agent 多轮工具编排。

## 🛠️ 工具列表

本服务器向 AI Agent 暴露以下工具：

| 工具名称 (Tool Name)              | 参数 (Parameters)                                 | 功能描述 (Description)                     |
| :-------------------------------- | :------------------------------------------------ | :----------------------------------------- |
| `cloud_music_login`               | 无                                                | 启动扫码登录流程 (模拟官方 App)。          |
| `cloud_music_status`              | 无                                                | 检查账号、控制通道、输入桌面和主窗口。     |
| `cloud_music_get_daily_recommend` | `limit`: 返回数量（默认 50）                      | 获取带位置编号的完整今日推荐列表。         |
| `cloud_music_my_playlists`        | 无                                                | 获取用户的所有歌单（包括创建的和收藏的）。 |
| `cloud_music_playlist_detail`     | `playlist_id`: 歌单 ID                            | 获取歌单详情及歌单内所有歌曲。             |
| `cloud_music_create_playlist`     | `name`: 歌单名称 `<br>privacy`: 是否隐私(默认否)  | 创建新歌单。                               |
| `cloud_music_add_to_playlist`     | `playlist_id`: 歌单 ID `<br>track_ids`: 歌曲 ID 列表 | 批量添加歌曲到指定歌单。                |
| `cloud_music_preview_bgm_playlist` | `tracks`: 歌曲清单 `<br>playlist_label`: 自定义文字 | 预览匹配结果，不修改账号数据。          |
| `cloud_music_import_bgm_playlist` | `tracks`: 歌曲清单 `<br>playlist_label`: 自定义文字 `<br>privacy`: 是否隐私 | 一步匹配、去重并创建或复用当天歌单。 |
| `cloud_music_search`              | `keyword`: 关键词 `<br>category`: 类型 `<br>limit`: 数量 | 按关键词搜索歌曲、专辑、歌手或歌单。   |
| `cloud_music_album_info`          | `album_id`: 专辑 ID                               | 获取专辑详情及歌曲列表。                   |
| `cloud_music_artist_info`         | `artist_id`: 歌手 ID                              | 获取歌手详情和热门歌曲 Top 10。            |
| `cloud_music_my_subscriptions`    | `category`: 'artists'/'albums'                    | 获取收藏的歌手或专辑列表。                 |
| `cloud_music_play`                | `id`: 歌曲或歌单 ID `<br>type`: `'song'`/`'playlist'` | 控制网易云官方客户端播放单曲或歌单，并校验实际播放状态。 |
| `cloud_music_play_daily`          | `position`: 从 1 开始的位置                       | 直接播放每日推荐第 N 首。                  |
| `cloud_music_search_and_play`     | `keyword`: 关键词 `<br>position`: 结果位置         | 搜索并直接播放第 N 个歌曲结果。            |

## 🚀 安装与使用

### 前置条件

- **操作系统**：macOS 或 Windows（新版官方客户端播放控制目前仅支持 Windows）
- **Python 版本**：3.10 或更高
  - macOS：通常自带，运行 `python3 --version` 检查
  - Windows：从 [python.org](https://www.python.org/downloads/) 下载安装
- **安装网易云音乐桌面客户端**
- **LLM 客户端**（如 Claude Desktop、OpenCode 等）

> **已知限制（Codex 隔离环境）**：当网易云音乐客户端完全退出时，MCP 目前不能可靠地自动启动客户端并建立控制通道。请先用普通 Windows 用户方式手动启动官方客户端，待主窗口出现后再调用播放 Tool。客户端已运行时，单曲、每日推荐、搜索后播放和歌单播放均可正常控制。`启动网易云音乐-MCP.cmd` 可用于手动启动和排查启动失败；不要从 Codex 内置终端运行该脚本。主界面、托盘和音频均由官方客户端提供。

### 安装步骤

#### 1. 安装 uv 包管理器

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

#### 2. 克隆项目并安装依赖

```bash
# 克隆项目
git clone https://github.com/Jas0nSt0ne/netease-cloud-music-mcp.git
cd netease-cloud-music-mcp

# 创建虚拟环境
uv venv

# 激活虚拟环境
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 安装项目（可编辑模式）
uv sync
```

### 配置 LLM 客户端

#### Claude Desktop

找到配置文件：

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

添加以下配置：

```json
{
  "mcpServers": {
    "netease-cloud-music": {
      "command": "/绝对路径到/netease-cloud-music-mcp/.venv/bin/netease-cloud-music-mcp",
      "enabled": true
    }
  }
}
```

> **重要**：将 `/绝对路径/到/netease-cloud-music-mcp` 替换为项目的实际绝对路径。Windows 用户请使用双反斜杠 `\\` 或正斜杠 `/`。旧命令 `cloud-music-mcp` 暂时保留为兼容别名。

#### 开启日志（可选）

如需调试，可在配置中添加环境变量：

```json
{
  "mcpServers": {
    "netease-cloud-music": {
      "command": "/绝对路径/到/netease-cloud-music-mcp/.venv/bin/netease-cloud-music-mcp",
      "enabled": true,
      "env": {
        "MCP_LOG_ENABLE": "true"
      }
    }
  }
}
```

**日志说明：**

- **默认状态**：日志功能默认关闭
- **开启后**：日志写入用户数据目录下的 `netease-cloud-music-mcp/logs/netease-cloud-music-mcp.log`，单文件 2 MB，保留 3 个轮转文件

### 使用方法

1. **重启 LLM 客户端**（如 Claude Desktop）
2. **登录网易云音乐**
   - 在对话中输入："帮我扫码登录网易云音乐"
   - AI 会调用 `cloud_music_login` 工具，弹出二维码
   - 必须使用已登录的手机端网易云音乐 App 内置“扫一扫”扫码并确认授权
   - 请勿使用微信、系统相机或普通浏览器扫码；这些方式只能打开链接，无法完成登录
   - 登录状态（Cookies）仅保存在本地，保护隐私

3. **开始使用**
   - 播放音乐："给我放首歌"
   - 播放推荐："播放每日推荐第 17 首"
   - 搜索并播放："播放王力宏的歌"
   - 获取推荐："看看今日推荐有什么"
   - 搜索歌曲："搜一下周杰伦的歌"
   - 创建歌单："帮我建个周杰伦热门歌曲的歌单"
   - 截图导入：发送片尾 BGM 清单截图，并说“直接做成影视剧博主BGM歌单”

#### 从截图导入 BGM

支持看图的 AI Agent 会先按截图从上到下整理歌名和歌手，再把结构化清单交给 MCP 搜索。用户不需要在两个工具之间做选择：说“直接做成歌单”时会一步完成；说“先识别一下，别创建”时只返回预览。

- 自定义名称“影视剧博主BGM”会生成 `20260830影视剧博主BGM` 这样的歌单名；不填写时生成 `20260830歌单`，日期和文字之间不加横杠、斜杠或空格。
- 重复歌曲自动跳过；若当天已有同名的自建歌单，则复用该歌单。
- 歌名与歌手均精确匹配的结果自动加入；Live、Remix、伴奏、翻唱或同名不同歌手等歧义版本不会擅自加入，而是返回候选等待确认。
- MCP 本身不内置 OCR；是否能直接读取截图取决于所使用的 AI 客户端是否支持图片输入，也可以直接粘贴文字歌曲清单。

### Windows 客户端状态

可在普通 Windows Terminal 中检查启动器状态：

```powershell
netease-cloud-music-mcp-client --status
netease-cloud-music-mcp-client --status --json
```

常用环境变量：

- `CLOUD_MUSIC_CLIENT_PATH`：覆盖 `cloudmusic.exe` 路径。
- `CLOUD_MUSIC_DEBUG_PORT`：覆盖本地控制端口，默认 `9222`。
- `NETEASE_CLOUD_MUSIC_MCP_DATA_DIR`：覆盖 Cookie 与日志目录。
- `CLOUD_MUSIC_MCP_DATA_DIR`：旧环境变量兼容别名。
- `MCP_LOG_ENABLE=true`：开启轮转日志。

## 🙏 来源与致谢

本项目最初基于 [Code-MonkeyZhang/cloud-music-mcp](https://github.com/Code-MonkeyZhang/cloud-music-mcp) 开发，并在其基础上继续完善网易云账号能力、歌单管理和 Windows 官方客户端播放控制。感谢原作者 Jonathan Zhang 的开源工作；原始提交作者信息与 MIT License 均予以保留。
