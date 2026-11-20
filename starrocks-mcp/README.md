# StarRocks 只读 MCP 服务

一个供团队内部使用的轻量 MCP 服务：通过 FastMCP 连接 StarRocks，提供数据库/表浏览、只读 SQL 查询和执行计划。支持本地 stdio 客户端，也支持供豆包工作伙伴等客户端访问的 Streamable HTTP / SSE；HTTP 通过 Bearer API Key 认证，可选验证飞书 aily 身份 JWT。不依赖 OAuth。

## 快速开始

需要 Python 3.10+。先复制 `.env.example` 并按需设置环境变量（程序不会自动加载 `.env` 文件）：

```bash
cp .env.example .env
# 编辑 .env；然后可以在当前 shell 加载它：
set -a; source .env; set +a
```

### uv

```bash
uv sync --extra dev
uv run starrocks-mcp                 # stdio
uv run starrocks-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

### pip / venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
starrocks-mcp                         # stdio
starrocks-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

HTTP 模式必须配置 `MCP_API_KEYS`，或明确设置 `MCP_ALLOW_NO_AUTH=true`（仅适用于受控测试环境）。服务 MCP 路径为 `/mcp`，无认证健康检查为 `/healthz`。`--transport`、`--host`、`--port` 命令行参数覆盖相应环境变量。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STARROCKS_HOST` | `localhost` | FE MySQL 协议地址 |
| `STARROCKS_PORT` | `9030` | FE MySQL 协议端口 |
| `STARROCKS_USER` | `root` | 数据库用户；生产环境应使用只读账号 |
| `STARROCKS_PASSWORD` | 空 | 数据库密码 |
| `STARROCKS_DEFAULT_DB` | 空 | 可选默认数据库 |
| `STARROCKS_ALLOWED_DATABASES` | 空 | 逗号分隔允许列表；为空时除系统库外均可访问。系统库 `information_schema`、`_statistics_`、`sys`、`starrocks_audit_db__` 始终隐藏/禁止，除非显式列出 |
| `QUERY_TIMEOUT_SECONDS` | `30` | StarRocks 查询超时；客户端读取超时为此值加 5 秒 |
| `MAX_ROWS` | `500` | 查询最大返回行数 |
| `MAX_RESULT_CHARS` | `50000` | JSON 结果软截断上限（字符数） |
| `MCP_TRANSPORT` | `stdio` | `stdio`、`streamable-http` 或 `sse` |
| `MCP_HOST` | `0.0.0.0` | HTTP 监听地址 |
| `MCP_PORT` | `8000` | HTTP 监听端口 |
| `MCP_API_KEYS` | 空 | 逗号分隔的 `名称=令牌`；名称写入审计日志，令牌只用于验证 |
| `MCP_ALLOW_NO_AUTH` | `false` | 是否允许无 API Key 启动 HTTP（不建议） |
| `AILY_JWT_SECRET` | 空 | aily JWT HS256 签名密钥 |
| `AILY_JWT_REQUIRED` | `false` | 是否要求 `x-aily-jwt` 请求头；启用时必须设置签名密钥 |
| `AUDIT_LOG_FILE` | 空 | 可选 JSONL 审计文件；无论是否配置，审计也会写到 stderr |

成功解析的 aily JWT 可包含 `user_id`（open id）、`tenant_id`、`email` 等字段，有效期由 `exp` 控制，验证时允许 30 秒时钟偏差。

## StarRocks 只读账号

请由 StarRocks 管理员按目标数据库授予最小权限。StarRocks 3.x 的授权语法：

```sql
CREATE USER 'mcp_readonly'@'%' IDENTIFIED BY 'replace-with-a-strong-password';
GRANT SELECT ON ALL TABLES IN DATABASE <db> TO USER 'mcp_readonly'@'%';
```

对该账号仅授予查询权限，不要授予 `INSERT`、`CREATE`、`ALTER`、`DROP` 或管理权限。共享集群可由 DBA 为查询账号配置资源组/工作负载限额，限制 CPU、内存等资源消耗。

## 通过 HTTPS 部署

只在受信网络中暴露服务，并在反向代理上终止 TLS（公网客户端必须使用 HTTPS）。例如 Nginx：

```nginx
server {
    listen 443 ssl;
    server_name starrocks-mcp.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

`streamable-http` 使用长连接/流式响应，代理需关闭 `proxy_buffering` 并设置足够长的读取超时。请在生产环境使用强随机 API Key，并通过部署平台的 Secret 管理功能提供密钥。

## MCP 客户端

以下 HTTP 示例中的 `https://mcp.example.com/mcp` 应替换为已配置 HTTPS 的公网地址，`<token>` 替换为 `MCP_API_KEYS` 中某个 API Key 对应的令牌。

### 豆包工作伙伴（飞书 aily）

1. 打开 `https://{公司前缀}.feishu.cn/ai/mcpservers`。
2. 点击「注册企业内部 MCP 服务」。
3. 请求地址填写 `https://<域名>/mcp`，Endpoint 类型选择 **Streamable HTTP**。
4. 添加请求头 `Authorization`，输入方式选择「固定值」，值填写 `Bearer <token>`。
5. 可选开启「JWT 身份令牌」，将编辑页显示的签名密钥配置到服务端 `AILY_JWT_SECRET`；需要强制身份令牌时同时设置 `AILY_JWT_REQUIRED=true`。
6. 设置可用范围。
7. 在智能体中选择「从 MCP 库添加」并启用工具。

豆包工作伙伴无法访问仅内网可达的地址。客户端从平台出口访问；如有防火墙，需放行其出口 IP（以飞书官方说明为准）。

### Cursor

在 Cursor MCP 配置文件（`mcp.json`）中添加：

```json
{
  "mcpServers": {
    "starrocks": {
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add --transport http starrocks https://mcp.example.com/mcp \
  --header "Authorization: Bearer <token>"
```

### Codex

在 `~/.codex/config.toml` 中配置远程 Streamable HTTP MCP（Codex 使用 `http_headers`）：

```toml
[mcp_servers.starrocks]
url = "https://mcp.example.com/mcp"
http_headers = { "Authorization" = "Bearer <token>" }
```

### Cherry Studio 和阿里云百炼

新建远程 MCP 服务，传输协议选 **Streamable HTTP**，URL 填写 `https://mcp.example.com/mcp`，并在自定义请求头中添加 `Authorization: Bearer <token>`。

### 本地 stdio

Cursor / Claude Code / Codex 等本地客户端可以直接启动 stdio 服务，无需 MCP API Key。例如 `mcp.json`：

```json
{
  "mcpServers": {
    "starrocks": {
      "command": "/path/to/starrocks-mcp/.venv/bin/starrocks-mcp",
      "env": {
        "STARROCKS_HOST": "127.0.0.1",
        "STARROCKS_PORT": "9030",
        "STARROCKS_USER": "mcp_readonly",
        "STARROCKS_PASSWORD": "replace-me",
        "STARROCKS_ALLOWED_DATABASES": "analytics"
      }
    }
  }
}
```

## 本地验证

以下命令在本仓库的 `starrocks-mcp/` 目录执行。首次启动本地 StarRocks all-in-one 容器：

```bash
docker run -d -p 9030:9030 -p 8030:8030 -p 8040:8040 --name sr starrocks/allin1-ubuntu
```

FE/BE 完成启动后，用 root 创建示例数据库、表和只读账号（`readpass` 仅供本地测试）：

```bash
./.venv/bin/python - <<'PY'
import pymysql

root = pymysql.connect(host="127.0.0.1", port=9030, user="root", password="", autocommit=True, charset="utf8mb4", connect_timeout=10)
with root.cursor() as cursor:
    cursor.execute("CREATE DATABASE IF NOT EXISTS demo")
    cursor.execute("CREATE TABLE IF NOT EXISTS demo.smoke_test (id INT, name VARCHAR(64)) ENGINE=OLAP DUPLICATE KEY(id) DISTRIBUTED BY HASH(id) BUCKETS 1 PROPERTIES (\"replication_num\" = \"1\")")
    cursor.execute("INSERT INTO demo.smoke_test VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma')")
    cursor.execute("CREATE USER IF NOT EXISTS 'mcp_readonly'@'%' IDENTIFIED BY 'readpass'")
    cursor.execute("GRANT SELECT ON ALL TABLES IN DATABASE demo TO USER 'mcp_readonly'@'%'")
root.close()
PY
```

在一个终端启动 Streamable HTTP 服务（API Key 为本地测试令牌）：

```bash
STARROCKS_HOST=127.0.0.1 STARROCKS_PORT=9030 STARROCKS_USER=mcp_readonly STARROCKS_PASSWORD=readpass STARROCKS_DEFAULT_DB=demo MCP_TRANSPORT=streamable-http MCP_API_KEYS=test=xxx ./.venv/bin/starrocks-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

在另一个终端运行自动冒烟测试，它会调用全部五个工具，并确认写 SQL 与无令牌请求被拒绝：

```bash
./.venv/bin/python scripts/e2e_smoke.py
```

也可手动使用 MCP Inspector：

```bash
npx @modelcontextprotocol/inspector
```

在 Inspector 中选择 **Streamable HTTP**，地址填写 `http://127.0.0.1:8000/mcp`，并在请求头添加 `Authorization: Bearer xxx`，连接后检查五个工具。

## 安全边界

1. **数据库账号只读**：优先依靠 StarRocks `SELECT` 最小权限，即使应用层出现问题也阻止写入。
2. **SQL AST 守卫**：仅接受单条只读查询，并对表引用执行数据库 allowlist / 系统库检查。
3. **资源与结果上限**：设置查询超时、数据库读取超时、返回行数和结果字符数上限。

查询结果会进入调用方模型的上下文，请避免查询或返回不必要的敏感数据，并谨慎配置客户端与数据库权限。
