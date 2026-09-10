# 腾讯会议报告解析服务部署文档

## 1. 服务说明

该服务用于根据腾讯会议纪要 TXT、公司名称、腾讯会议 ID、产品/订单 ID、律师会前勾选内容，生成两份 Word 文书：

- 合规计划书
- 文书清单

正式对接推荐使用：

```text
POST /api/process
GET  /api/task/{task_id}/stream
```

处理完成后，服务会将 `.docx` 文件上传 OSS，并将文件 URL 保存到 SQL Server。

## 2. 端口说明

当前项目统一使用 `8124` 作为默认端口：

| 启动方式 | 默认/建议端口 | 说明 |
|----------|---------------|------|
| 本地开发命令 | `8124` | 与 `main.py` 保持一致 |
| Docker / docker-compose | `8124` | Dockerfile 和 compose 当前暴露该端口 |

如本地调试需要临时换端口，可以在 `uvicorn` 命令中手动修改 `--port`。

## 3. 依赖服务

| 服务 | 用途 | 必须 |
|------|------|------|
| 火山引擎豆包模型 | 生成文书内容 | 是 |
| 阿里云 OSS | 保存生成后的 Word 文件 | 是 |
| SQL Server | 保存文书文件记录 | 是 |

## 4. 环境变量

部署前在项目根目录创建 `.env`：

```env
# LLM配置（火山引擎豆包）
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=your_api_key_here
LLM_MODEL=doubao-seed-2-0-mini-260428

# 数据库配置（SQL Server）
DB_SERVER=your_db_server,1433
DB_DATABASE=your_database_name
DB_USERNAME=your_username
DB_PASSWORD=your_password

# OSS配置（阿里云）
OSS_ACCESS_KEY=your_access_key
OSS_SECRET_KEY=your_secret_key
OSS_ENDPOINT=https://oss-cn-qingdao.aliyuncs.com
OSS_BUCKET_NAME=your_bucket_name
```

安全要求：

- `.env` 不要提交到代码仓库
- Linux 服务器建议设置权限：`chmod 600 .env`

## 5. 本地启动

PowerShell：

```powershell
cd meeting_parser
python -m uvicorn main:app --host 127.0.0.1 --port 8124 --reload
```

本机访问：

```text
http://127.0.0.1:8124
http://127.0.0.1:8124/health
```

如需同一 WiFi 下其他设备访问：

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8124 --reload
```

访问地址：

```text
http://你的电脑IP:8124
```

## 6. Docker 部署

### 6.1 构建并启动

```bash
cd meeting_parser
docker compose up -d --build
```

### 6.2 验证

```bash
curl http://localhost:8124/health
```

期望返回：

```json
{"status":"ok"}
```

### 6.3 常用命令

```bash
docker compose logs -f
docker compose ps
docker compose restart
docker compose stop
docker compose start
docker compose down
```

## 7. 主接口

### 7.1 提交任务：POST `/api/process`

请求体只接收以下 5 个业务字段：

```json
{
  "company_name": "德云逗笑社",
  "meeting_id": "92b0a068-0dfa-4b0a-b261-300c1462f5ce",
  "order_id": "26062609150101900",
  "file_url": "https://example.com/meeting.txt",
  "PreMeetingPreparation": {
    "groupOne": ["劳动合同", "劳务协议", "退休返聘协议"],
    "groupTwo": ["转正审批表", "延长试用期协议"]
  }
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `company_name` | string | 是 | 公司名称，合规计划书封面使用该字段 |
| `meeting_id` | string | 是 | 腾讯会议 ID / 会议记录 ID |
| `order_id` | string | 是 | 产品 ID / 订单 ID |
| `file_url` | string | 是 | 腾讯会议纪要 TXT 文件 URL，必须服务端可访问 |
| `PreMeetingPreparation` | object | 否 | 律师会前勾选内容，用于补充文书清单筛选 |

返回：

```json
{
  "success": true,
  "task_id": "task_xxxxxxxxxxxx",
  "message": "任务已提交，正在处理..."
}
```

### 7.2 查询任务状态：GET `/api/task/{task_id}/stream`

该接口为 SSE（Server-Sent Events）流式接口，实时推送任务状态变化。

请求示例：

```bash
curl -N http://localhost:8124/api/task/task_xxxxxxxxxxxx/stream
```

任务状态：

| 状态 | 说明 |
|------|------|
| `pending` | 任务已提交，等待处理 |
| `generating_compliance_plan` | 正在生成合规计划书 |
| `compliance_plan_done` | 合规计划书生成完成 |
| `generating_document_list` | 正在生成文书清单 |
| `document_list_done` | 文书清单生成完成 |
| `completed` | 处理完成 |
| `failed` | 处理失败 |
| `superseded` | 被同一 `order_id + meeting_id` 的新任务覆盖 |

SSE 推送的消息格式为 `event: task` + `data: {JSON}`，其中 `data` 包含：

```json
{
  "task_id": "task_xxxxxxxxxxxx",
  "meeting_id": "92b0a068-0dfa-4b0a-b261-300c1462f5ce",
  "order_id": "26062609150101900",
  "status": "completed",
  "progress": "处理完成",
  "result": {
    "doc1_url": "https://.../合规计划书.docx",
    "doc2_url": "https://.../文书清单.docx",
    "document_counts": {},
    "risk_facts": []
  },
  "error": null
}
```

失败时 `status` 为 `failed`，`error` 字段包含错误原因。被覆盖时 `status` 为 `superseded`。

连接期间若 15 秒无状态变化，服务端会发送 `event: ping` 心跳包，客户端可据此保持连接。

## 8. 下载文书

任务 `status=completed` 后：

- `result.doc1_url`：合规计划书下载地址
- `result.doc2_url`：文书清单下载地址

直接在浏览器打开 URL 即可下载或预览。

## 9. 生成和覆盖规则

### 9.1 合规计划书

- 使用 `/api/process.company_name` 作为封面公司名称
- 不从会议纪要中推断公司名称
- 使用 `reference_templates/compliance_plan.docx` 作为内容参考和 Word 样式模板

### 9.2 文书清单

- 使用腾讯会议纪要、合规计划书、律师勾选补充内容共同筛选本次涉及文书
- 不输出模板全集
- 总览表和各文书作用说明一一对应
- 总览表与各文书作用说明按模板分页
- 各文书作用说明中的编号全局连续递增
- 使用 `reference_templates/document_list.docx` 作为内容参考和 Word 样式模板

### 9.3 重复提交

同一 `order_id + meeting_id + 文书类型` 只保留最新版本：

- OSS 路径固定，新文件覆盖旧文件
- 数据库记录存在则更新，不存在则插入
- 同一 `order_id + meeting_id` 短时间重复提交，以最后一次提交的任务为准
- 旧任务如果被新任务覆盖，会标记为 `superseded`

## 10. 数据库记录

表名：

```text
dbo.ent_wechat_order_document
```

保存逻辑：

- 按 `MeetingRecordGuid + OrderCustomerId + DocType + IsDel=0` 查找旧记录
- 找到则更新 `FileUrl`、`FileName`、`Status`、`CreateDate`
- 找不到则插入新记录

主要字段：

| 字段 | 说明 |
|------|------|
| `DocRecordGuid` | 文书记录 ID |
| `MeetingRecordGuid` | 会议 ID |
| `OrderCustomerId` | 产品/订单 ID |
| `DocType` | 文书类型：合规计划书 / 文书清单 |
| `FileUrl` | OSS 文件 URL |
| `FileName` | 文件名 |
| `Status` | 状态 |
| `CreateDate` | 创建/更新时间 |
| `IsDel` | 是否删除 |

## 11. 日志

容器日志：

```bash
docker compose logs -f
```

应用日志：

```bash
tail -f logs/app.log
```

## 12. 常见问题

### 12.1 端口访问不了

- 本地开发确认是否启动在 `8124`
- Docker 部署确认是否启动在 `8124`
- 局域网访问时，启动 host 需要是 `0.0.0.0`
- 检查防火墙是否放行端口

### 12.2 `/api/process` 返回 422

常见原因：

- `PreMeetingPreparation` 传成了字符串，而不是 JSON 对象
- 缺少必填字段 `company_name`、`meeting_id`、`order_id`、`file_url`
- `file_url` 写成了 Markdown 链接格式，例如 `[url](url)`

正确示例：

```json
"PreMeetingPreparation": {
  "groupOne": ["劳动合同"]
}
```

错误示例：

```json
"PreMeetingPreparation": "{\"groupOne\":[\"劳动合同\"]}"
```

### 12.3 下载地址打开还是旧文件

如果 OSS 或浏览器有缓存，可以在下载 URL 后加时间戳：

```text
https://.../合规计划书.docx?t=当前时间戳
```

### 12.4 任务状态查不到

当前任务状态保存在进程内存中。服务重启后，之前的 `task_id` 查询状态会丢失。正式高可靠部署建议接入 Redis/Celery 或数据库任务表。

## 13. 上线建议

- 使用 Nginx 做反向代理和 HTTPS
- `.env` 使用服务器密钥管理或安全权限
- 高并发场景接入任务队列，限制同时生成任务数量
- 增加任务状态持久化，避免重启后状态丢失
- 对 OSS 下载链接配置合理的访问权限
