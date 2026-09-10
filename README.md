# meeting_parser

腾讯会议纪要解析服务。后端是 FastAPI，接收会议纪要文件和律师会前勾选内容，生成两份 Word 文书：

- 合规计划书
- 文书清单

## 1. 项目介绍

服务有两套使用方式：

- 页面调试流程：上传本地 TXT/DOCX 会议纪要，流式生成内容，并下载 Word。
- 正式对接流程：调用 `/api/process` 提交后台任务，服务下载会议文件，生成 Word，上传 OSS，并把文件记录写入 SQL Server。

当前文书清单规则：

- 文书清单只按律师在 `PreMeetingPreparation` 中勾选的具体文书生成。
- 保留八大类分组展示。
- 总览表展示具体文书名称，不把具体文书合并成旧的通用名称。
- 各文书作用说明来自 `document_selection.py` 的固定说明，不再由模型自由生成。
- 会议纪要仍用于生成合规计划书和抽取风险事实，但不再用于补充未勾选的文书清单。

## 2. 环境地址

| 环境 | 地址/路径 | 说明 |
|---|---|---|
| 本地开发 | `http://127.0.0.1:8124/` | 本地启动后访问 |
| 测试环境 | `http://<测试服务器IP>:8124/` | 部署后的测试服务 |
| 正式环境 | `http://<正式服务器IP>:8124/` | 部署后的正式服务 |
| 服务端口 | `8124` | FastAPI / Docker 暴露端口 |

## 3. 架构

```text
main.py
  ├─ FastAPI 路由
  ├─ 上传会议文件 / 下载 URL 文件
  ├─ 调用 workflow.run_workflow
  ├─ 生成合规计划书和文书清单
  ├─ docx_exporter 输出 Word
  ├─ oss_client 上传 OSS
  └─ db_client 写入 SQL Server 文书记录
```

核心文件：

| 文件/目录 | 说明 |
|---|---|
| `main.py` | FastAPI 入口，接口、任务提交、SSE 推送 |
| `workflow.py` | 串行生成合规计划书、风险事实、文书清单 |
| `prompts.py` | 合规计划书 Prompt、风险事实 Prompt、固定文书清单正文生成 |
| `document_selection.py` | 八大类文书、具体文书名、固定说明、律师勾选解析 |
| `docx_exporter.py` | 将文本渲染为 Word，套用参考模板 |
| `download_utils.py` | 下载 URL 文件，支持 TXT/DOCX 内容提取 |
| `db_client.py` | SQL Server 文书状态和文件记录写入 |
| `oss_client.py` | 阿里云 OSS 上传 |
| `task_manager.py` | 内存任务状态、同订单同会议覆盖控制、SSE 订阅 |
| `reference_templates/` | Word 样式参考模板 |
| `static/index.html` | 本地调试页面 |
| `logs/app.log` | 应用日志 |

## 4. 配置

所有敏感配置通过 `.env` 文件注入，示例见 `.env.example`：

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

> 安全提示：`.env` 文件包含真实密钥，切勿提交到代码仓库。

OSS 上传路径：

```text
upload/app/orders/{order_id}/{meeting_id}/合规计划书.docx
upload/app/orders/{order_id}/{meeting_id}/文书清单.docx
```

如果没有配置 `OSS_CUSTOM_DOMAIN`，返回 URL 格式为：

```text
https://{OSS_BUCKET_NAME}.{OSS_ENDPOINT域名}/upload/app/orders/{order_id}/{meeting_id}/{文件名}
```

## 5. 数据库

连接信息通过 `.env` 配置（`DB_SERVER`、`DB_DATABASE`、`DB_USERNAME`、`DB_PASSWORD`），使用 ODBC Driver 17 for SQL Server。

涉及表：

| 表名 | 用途 |
|---|---|
| `dbo.ent_wechat_order_document` | 保存合规计划书、文书清单的文件 URL、文件名和状态 |
| `dbo.ent_wechat_document_template` | 旧逻辑/兜底逻辑中用于统计文书模板数量 |

`ent_wechat_order_document` 写入规则：

- 业务键：`MeetingRecordGuid + OrderCustomerId + DocType + IsDel=0`。
- 提交任务时先把两份文书状态写为 `pending`。
- 开始生成后状态更新为 `generating`。
- 上传成功后写入 `FileUrl`、`FileName`，状态更新为 `completed`。
- 同一会议和订单重复提交时，只保留最新任务写入结果。

## 6. 文书清单规则

八大类分组来自 `DOCUMENT_OVERVIEW_GROUPS`：

```text
一、用工模式与劳动合同签署
二、社保、公积金及工伤合规
三、规章制度合规
四、工时、加班与休假合规
五、员工入职合规
六、薪资发放合规
七、员工离职合规
八、专项协议合规
```

律师勾选分组映射：

| 入参字段 | 对应分类 |
|---|---|
| `groupOne` | 一、用工模式与劳动合同签署 |
| `groupTwo` | 一、用工模式与劳动合同签署 |
| `groupThree` | 二、社保、公积金及工伤合规 |
| `groupFour` | 三、规章制度合规 |
| `groupFive` | 四、工时、加班与休假合规 |
| `groupSix` | 五、员工入职合规 |
| `groupSeven` | 六、薪资发放合规 |
| `groupEight` | 七、员工离职合规 |
| `groupNine` | 八、专项协议合规 |

支持的勾选值：

- 字符串：`"劳动合同（缴纳社保）"`。
- 带书名号字符串：`"《劳动合同（缴纳社保）》"`。
- 对象：读取 `templateName`、`TemplateName`、`documentName`、`DocumentName`、`name`、`Name` 中第一个有值字段。

生成规则：

- `build_final_document_counts()` 当前只合并 `build_pre_meeting_document_counts(pre_meeting)`。
- 具体文书名必须能在 `DOCUMENT_CATEGORY_BY_TITLE` 中匹配。
- 份数默认每次勾选计 `1`，重复勾选会累加。
- 输出顺序按八大类和 `DOCUMENT_OVERVIEW_GROUPS` 中的文书顺序排序。
- 说明文字通过 `document_description_for_title()` 读取固定说明。

## 7. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/` | 返回 `static/index.html` 调试页面 |
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/upload` | 上传 TXT/DOCX 会议纪要，返回 `session_id` |
| `POST` | `/api/generate/stream` | 页面调试用，根据 `session_id` 流式生成两份文书 |
| `GET` | `/api/result/{session_id}` | 查询页面调试流程的生成文本 |
| `GET` | `/api/download/{session_id}/{doc_index}` | 页面调试流程下载 Word，`doc_index=1/2` |
| `POST` | `/api/process` | 正式对接提交后台任务 |
| `GET` | `/api/task/{task_id}/stream` | SSE 实时推送任务状态 |

当前代码没有 `GET /api/task/{task_id}` 普通查询接口，任务状态查询使用 `/api/task/{task_id}/stream`。

### `/api/process`

请求体：

```json
{
  "company_name": "某某公司",
  "meeting_id": "92b0a068-0dfa-4b0a-b261-300c1462f5ce",
  "order_id": "26062609150101900",
  "file_url": "https://example.com/meeting.docx",
  "PreMeetingPreparation": {
    "groupOne": ["劳动合同（缴纳社保）", "劳务协议"],
    "groupThree": ["工资条模板（缴纳社保）"]
  }
}
```

返回：

```json
{
  "success": true,
  "task_id": "task_xxxxxxxxxxxx",
  "message": "任务已提交，正在处理..."
}
```

任务状态字段：

| 状态 | 说明 |
|---|---|
| `pending` | 任务已提交，等待处理 |
| `generating_compliance_plan` | 正在生成合规计划书 |
| `compliance_plan_done` | 合规计划书生成完成 |
| `generating_document_list` | 正在生成文书清单 |
| `document_list_done` | 文书清单生成完成 |
| `completed` | 处理完成 |
| `failed` | 处理失败 |
| `superseded` | 已被同一会议和订单的新任务覆盖 |

完成后的 `result` 包含：

```json
{
  "doc1_url": "https://.../合规计划书.docx",
  "doc2_url": "https://.../文书清单.docx",
  "document_counts": {
    "劳动合同（缴纳社保）": 1
  },
  "risk_facts": []
}
```

## 8. 运行

本地安装依赖：

```powershell
cd meeting_parser
pip install -r requirements.txt
```

本地启动：

```powershell
python main.py
```

或使用 uvicorn：

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 8124 --reload
```

访问：

```text
http://127.0.0.1:8124/
http://127.0.0.1:8124/health
```

## 9. Docker 部署

当前 Docker 配置：

```text
基础镜像：python:3.11-bullseye
SQL Server Driver：msodbcsql17
OpenSSL：MinProtocol 降到 TLSv1.0，SECLEVEL 降到 1
Python 依赖源：清华 PyPI
端口：8124:8124
容器名：meeting_parser
镜像名：meeting_parser:latest
```

部署命令：

```bash
cd /path/to/meeting_parser
docker compose down
docker compose up -d --build
docker compose logs -f --tail=100
```

验证：

```bash
curl http://127.0.0.1:8124/health
```

期望返回：

```json
{"status":"ok"}
```

只要改了 `Dockerfile`、系统依赖、Python 依赖或代码，都需要重新构建镜像：

```bash
docker compose up -d --build
```

## 10. 常见问题

| 问题 | 排查方向 |
|---|---|
| SQL Server 报 `unsupported protocol` | 确认镜像已按当前 Dockerfile 重新构建，OpenSSL 兼容配置已生效 |
| 容器里数据库连不上 | 检查 `.env` 是否挂载、`DB_SERVER` 网络是否通、ODBC Driver 17 是否安装 |
| OSS 上传失败 | 检查 OSS key、bucket、endpoint、目标路径权限 |
| 任务状态查不到 | `task_manager` 是内存状态，服务重启后旧 `task_id` 会丢失 |
| 重复提交结果被覆盖 | 同一 `meeting_id + order_id` 只保留最新任务，旧任务会变成 `superseded` |
| 文书清单缺少某份文书 | 检查 `PreMeetingPreparation` 是否勾选了具体文书名，名称是否在 `DOCUMENT_OVERVIEW_GROUPS` 中 |
| 文书说明不符合预期 | 固定说明在 `document_selection.py` 的 `DOCUMENT_DESCRIPTIONS` 中维护 |
| Word 格式异常 | 检查 `reference_templates/compliance_plan.docx` 和 `reference_templates/document_list.docx` 是否存在 |
