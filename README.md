# Dataset Forge

基于 Flask + SQLite + React + Vite 的图片训练数据集生成平台骨架。当前版本覆盖：

- Token 鉴权与演示账号
- 任务配置向导
- Prompt 预览与多样性变体生成
- 图片生成进度页与模拟结果画廊
- 数据增强、自动标注微服务、导出操作流
- Docker / docker-compose / GitHub Actions CI

## Monorepo 结构

```text
backend/    Flask REST API
frontend/   React + Vite UI
annotator/  Flask annotation microservice
```

## 本地开发

1. 复制环境变量：

```bash
cp .env.example .env
```

2. 使用 Docker Compose 启动：

```bash
docker compose up --build
```

3. 打开：

- 前端：`http://localhost:4173`
- 后端：`http://localhost:8000/api/v1/health`

数据库说明：

- Docker Compose 默认使用 SQLite，数据库文件位于容器内 `/app/storage/dataset_gen.db`
- 本地直接运行后端时，默认数据库文件位于 `backend/instance/dataset_gen_dev.db`
- `DATABASE_URL` 仍可覆盖，但项目默认链路已经统一到 SQLite

## 演示账号

- 邮箱：`demo@dataset.local`
- 密码：`Dataset123!`

## 后端说明

- 使用应用工厂模式与 SQLAlchemy 模型层
- Token 鉴权基于 JWT
- API Key 使用 AES-GCM 加密存储
- `gemini` provider 已接入 Google 官方 Imagen REST 适配层，调用失败会直接暂停任务并返回错误
- `jimeng` provider 已接入火山引擎官方 Seedream 图片生成接口，默认模型为 `doubao-seedream-3-0-t2i-250415`
- 标注链路已拆成独立微服务，后续可直接替换为真实 YOLO 推理

主要 REST API：

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/system/providers`
- `GET /api/v1/system/dashboard`
- `POST /api/v1/tasks/prompt-preview`
- `GET /api/v1/tasks`
- `POST /api/v1/tasks`
- `PATCH /api/v1/tasks/:id`
- `POST /api/v1/tasks/:id/start`
- `POST /api/v1/tasks/:id/retry`
- `POST /api/v1/tasks/:id/augment`
- `POST /api/v1/tasks/:id/annotate`
- `POST /api/v1/tasks/:id/export`
- `GET /api/v1/tasks/:id/exports/:version/download`

Gemini 生成说明：

- 默认模型：`imagen-4.0-generate-001`
- 请求走官方 Gemini Imagen `:predict` REST 接口
- 当前按任务轮询进度触发逐张生成；若 API 不可用或 provider 未实现，会暂停任务而不是回退

Jimeng 生成说明：

- 当前实现基于火山引擎官方图片生成 API 文档接入
- 默认 Base URL：`https://operator.las.cn-beijing.volces.com/api/v1`
- 默认模型：`doubao-seedream-3-0-t2i-250415`
- 请求使用 `Authorization: Bearer <API_KEY>`，返回格式使用 `b64_json`

## 前端说明

- React 18 + TypeScript + Vite
- Zustand 管理认证与任务草稿
- 响应式黑白灰工作台风格
- 向导页支持实时 Prompt 预览与本地草稿恢复
- 任务详情页轮询生成进度并串联增强、标注、导出
- 下载动作通过带 token 的 blob 流方式完成，适配跨端口部署

## 已知边界

- WebSocket、Bull、真实图像生成 API 尚未接入
- 数据导出会生成真实 ZIP；只有在任务确实生成出图片文件后才会被打包
- 当前使用 `AUTO_CREATE_SCHEMA=true` 自动建表，生产环境建议切换为 Alembic/Flask-Migrate
