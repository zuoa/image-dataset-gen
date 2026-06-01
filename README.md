# Dataset Forge

基于 Flask + SQLite + React + Vite 的图片训练数据集生成平台骨架。当前版本覆盖：

- Token 鉴权与演示账号
- 数据集管理与批次化生成
- Prompt 预览与多样性变体生成
- 数据集样本池、导入、增强、自动标注与导出
- Docker / docker-compose / GitHub Actions CI

## Monorepo 结构

```text
backend/    Flask REST API
frontend/   React + Vite UI
annotator/  Flask annotation microservice
trainer/    YOLOv8 training worker service
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

- 账号：`dataset`
- 密码：`Dataset123!`

JWT 说明：

- Access token 默认有效期为 7 天
- 可通过 `JWT_ACCESS_TOKEN_EXPIRES_DAYS` 覆盖

## 后端说明

- 使用应用工厂模式与 SQLAlchemy 模型层
- Token 鉴权基于 JWT
- API Key 使用 AES-GCM 加密存储
- `gemini` provider 已接入 Google 官方 Imagen REST 适配层，调用失败会直接暂停生成批次并返回错误
- `jimeng` provider 已接入火山引擎官方 Seedream 图片生成接口，默认模型为 `doubao-seedream-3-0-t2i-250415`
- 导入上限默认 `MAX_IMPORTED_IMAGES=2000`，本地视频导入支持按帧间隔抽帧生成底库图片，Roboflow 导入支持下载 YOLOv8 数据集并导入检测框标注
- 标注链路已拆成独立微服务，后续可直接替换为真实 YOLO 推理

主要 REST API：

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/system/providers`
- `GET /api/v1/system/dashboard`
- `GET /api/v1/datasets`
- `POST /api/v1/datasets`
- `GET /api/v1/datasets/:id`
- `PATCH /api/v1/datasets/:id`
- `DELETE /api/v1/datasets/:id`
- `POST /api/v1/datasets/generation/prompt-preview`
- `POST /api/v1/datasets/assist-subject`
- `POST /api/v1/datasets/:id/tasks/generation`
- `GET /api/v1/datasets/:id/tasks/:taskId`
- `POST /api/v1/datasets/:id/tasks/:taskId/start`
- `POST /api/v1/datasets/:id/tasks/:taskId/retry`
- `POST /api/v1/datasets/:id/tasks/import`
- `POST /api/v1/datasets/:id/tasks/import/video`
- `POST /api/v1/datasets/:id/tasks/import/roboflow`
- `POST /api/v1/datasets/:id/tasks/augmentation`
- `PATCH /api/v1/datasets/:id/selection`
- `PATCH /api/v1/datasets/:id/images/:imageId/annotations`
- `POST /api/v1/datasets/:id/annotate`
- `POST /api/v1/datasets/:id/export`
- `GET /api/v1/datasets/:id/exports/:version/download`
- `POST /api/v1/datasets/:id/training-jobs`
- `GET /api/v1/datasets/:id/training-jobs`
- `GET /api/v1/datasets/:id/training-jobs/:jobId`
- `GET /api/v1/datasets/:id/training-jobs/:jobId/artifacts/:artifactId/download`

训练 worker API 使用 `X-Training-Worker-Token: <TRAINING_WORKER_TOKEN>`：

- `POST /api/v1/training/workers/register`
- `POST /api/v1/training/workers/:workerId/heartbeat`
- `POST /api/v1/training/workers/:workerId/poll`
- `GET /api/v1/training/jobs/:jobId/dataset.zip`
- `PATCH /api/v1/training/jobs/:jobId/status`
- `POST /api/v1/training/jobs/:jobId/artifacts`

Gemini 生成说明：

- 默认模型：`imagen-4.0-generate-001`
- 请求走官方 Gemini Imagen `:predict` REST 接口
- 当前按生成批次轮询进度触发逐张生成；若 API 不可用或 provider 未实现，会暂停批次而不是回退

Jimeng 生成说明：

- 当前实现基于火山引擎官方图片生成 API 文档接入
- 默认 Base URL：`https://operator.las.cn-beijing.volces.com/api/v1`
- 默认模型：`doubao-seedream-3-0-t2i-250415`
- 请求使用 `Authorization: Bearer <API_KEY>`，返回格式使用 `b64_json`

Roboflow 导入说明：

- 前端导入弹窗手动填写 Roboflow API Key、workspace、project 和 version；API Key 只随本次请求发送，不保存到后端配置或数据库
- `MAX_IMPORTED_IMAGES` 控制单次本地 ZIP、视频抽帧或 Roboflow 导入上限，默认 `2000`
- 当前固定下载 `yolov8` 格式，支持 object detection 的 YOLO 标签；classification、segmentation 和 oriented box 标注不在第一版范围内

## 前端说明

- React 18 + TypeScript + Vite
- Zustand 管理认证与模型配置
- 响应式黑白灰工作台风格
- 数据集创建页支持先定义长期信息，再在详情页内管理批次
- 生成批次页支持实时 Prompt 预览
- 数据集详情页统一串联导入、增强、标注、导出与批次追踪
- 数据集详情页支持创建 YOLOv8 检测训练作业、查看进度、指标和下载模型产物
- 下载动作通过带 token 的 blob 流方式完成，适配跨端口部署

## 训练 worker

第一版训练链路面向 YOLOv8 detection：

1. 前端在数据集详情页创建训练作业。
2. 后端生成 YOLO 数据集 ZIP，并把训练作业置为 `queued`。
3. GPU 服务器上的 `trainer` 服务用共享 `TRAINING_WORKER_TOKEN` 注册到后端。
4. worker 轮询任务，下载 ZIP，执行 Ultralytics 训练。
5. worker 上传 `best.pt`、`last.pt`、`results.csv` 和 `metrics.json`，后端统一提供鉴权下载。

训练 worker 作为独立 GPU 服务部署，不再放在主 `docker-compose.yml` 的 profile 中。镜像由单独的 GitHub Actions workflow 发布到 GHCR：

- `ghcr.io/<owner>/dataset-gen-trainer:latest`
- `ghcr.io/<owner>/dataset-gen-trainer:sha-<commit>`

本地或远端 GPU 服务器启动训练 worker：

```bash
TRAINER_BACKEND_URL=http://<backend-host>/api/v1 \
TRAINER_WORKER_TOKEN=<与后端 TRAINING_WORKER_TOKEN 一致> \
TRAINER_WORKER_ID=<稳定 worker id> \
docker compose -f docker-compose.trainer.yml up -d
```

跨服务器部署时，在 GPU 服务器安装 NVIDIA Container Toolkit，并配置：

- `TRAINER_IMAGE=ghcr.io/<owner>/dataset-gen-trainer:latest`
- `TRAINER_BACKEND_URL=https://<platform-host>/api/v1`
- `TRAINER_WORKER_TOKEN=<与后端 TRAINING_WORKER_TOKEN 一致>`
- `TRAINER_WORKER_ID=<稳定 worker id>`
- `TRAINER_WORKER_NAME=<展示名>`
- `TRAINER_WORK_ROOT=/app/work`
- `TRAINER_MODEL_DIR=/app/models`

`docker-compose.trainer.yml` 会持久化 `/app/work` 和 `/app/models`，后者用于缓存 YOLO 权重；如果模型文件已经存在，会优先复用本地文件。

## 已知边界

- WebSocket、Bull、真实图像生成 API 尚未接入
- 数据导出会生成真实 ZIP；只有在数据集样本池中确实存在图片文件后才会被打包
- 当前使用 `AUTO_CREATE_SCHEMA=true` 自动建表，生产环境建议切换为 Alembic/Flask-Migrate
