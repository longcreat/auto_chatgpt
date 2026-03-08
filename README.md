# AutoChatGPT Manager

本地 OpenAI/Codex 账号与密钥管理系统，提供：

- 账号台账管理
- API key / access token 管理
- 域名邮箱别名台账
- 本地 Codex 代理切换，地址固定为 `http://127.0.0.1:8000/v1`

默认不启用 ChatGPT 消费者账号自动注册和网页会话凭证抓取。

## 快速开始

### 1. 分两个终端启动

Windows:

```bat
run_backend.bat
```

Linux / macOS:

```bash
chmod +x run_backend.sh run_frontend.sh
./run_backend.sh
```

另开第二个终端：

Windows:

```bat
run_frontend.bat
```

Linux / macOS:

```bash
./run_frontend.sh
```

脚本会自动：

- 在仓库根目录创建 `.venv`
- 将后端依赖安装到 `.venv`
- 启动 FastAPI: `http://127.0.0.1:8000`
- 启动 Vite: `http://127.0.0.1:5173`

本地开发默认使用 `5173`，避免常见的 `3000` 端口冲突。Docker 部署仍暴露 `3000`。

`start.bat` / `start.sh` 现在只负责提示这两个命令，不再自动帮你开窗口。

### 3. 配置 Codex

PowerShell:

```powershell
$env:OPENAI_API_BASE="http://127.0.0.1:8000/v1"
```

Bash:

```bash
export OPENAI_API_BASE="http://127.0.0.1:8000/v1"
```

切换管理界面中的激活账号后，Codex 无需重启。

## 支持的能力

- Codex 代理只使用激活账号的 `api_key` 或 `access_token`
- 管理接口只返回密钥预览值，不返回原始 token
- `.env`、`.venv`、数据库文件和前端构建产物默认被 `.gitignore` 忽略

> **配置说明**：首次启动后在前端「域名邮箱 → 系统配置」Tab 中填写域名、IMAP 收信设置和代理，无需手动编辑 `.env`。

## 自动注册

支持全程 HTTP 协议（curl_cffi TLS 指纹模拟）自动注册 ChatGPT 账号，无需浏览器。

注册流程（均在 UI 中完成）：
1. 「域名邮箱 → 系统配置」配置域名和 IMAP
2. 「域名邮箱 → 邮箱管理」批量生成邮箱别名
3. 「域名邮箱 → 批量注册」提交注册任务
4. 「域名邮箱 → 注册任务」查看进度和日志

## Docker

仍可使用 Docker Compose：

```bash
docker-compose up --build
```

默认暴露：

- `http://127.0.0.1:3000`
- `http://127.0.0.1:8000`

## 项目结构

```text
auto_chatgpt/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── serializers.py
│   │   ├── schemas.py
│   │   ├── routers/
│   │   └── services/
│   ├── requirements.txt
│   └── requirements-unsupported-automation.txt
├── frontend/
├── .env.example
├── .gitignore
├── start.bat
└── start.sh
```
