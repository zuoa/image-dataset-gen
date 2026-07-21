# Dataset Forge

面向小团队单机生产部署的图片数据集平台。主链路由 React、Flask、PostgreSQL、Redis/Celery 和可独立部署的 GPU trainer/segmenter 组成，支持图片生成、导入、增强、版本化标注、导出、训练与推理测试。

## Supervision 质量闭环

- 本地 ZIP 可自动识别并导入 YOLO、COCO、Pascal VOC，也继续支持纯图片压缩包；标注和数据集划分会一并保留。
- YOLO、COCO、Pascal VOC、CSV 导出支持单图多目标，并附带 `dataset-manifest.json`，将训练样本映射回平台图片与标注版本。
- 离线增强固定使用 MIT 许可的 Albumentations 2.0.8；新版策略按几何、目标遮挡、光照和成像退化分族进行概率编排，支持 bbox-safe 裁切、目标框内遮挡、仿射变化、色温、压缩与低清退化。图片与 YOLO 检测框保持同步并过滤低可见度目标；增强样本会记录源图谱系，导出时与源图保持在同一 train/val/test 集合。
- 数据集详情页可手动运行质量检查，识别缺失/空标注、越界与异常框、重复框、重复或损坏图片，并维护问题状态。
- YOLOv8/YOLO11 训练完成后由 trainer 自动运行 Supervision 评测，生成 mAP、分类指标、混淆矩阵及误检/漏检/类别混淆问题，回流到同一质量面板。
- Roboflow 下载能力保留。API Key 通过“Roboflow 连接”一次验证后加密保存，后续下载只提交连接 ID；后台导入任务不会把明文密钥写入响应或日志。

详细设计见 [架构说明](docs/architecture.md)，部署、备份和故障处理见 [运维手册](docs/operations.md)。

## 服务结构

```text
frontend/   React 18 + TypeScript + Vite；Nginx 统一入口和受保护文件转发
backend/    Flask API、SQLAlchemy 领域模型、Alembic 迁移、Celery worker
trainer/    可部署到 GPU 主机的 YOLO worker
segmenter/  可选的 SAM 2.1 交互分割服务，为目标检测标注提供点击选框
annotator/  旧的 mock 标注服务，仅保留兼容测试，不进入生产 Compose
```

生产数据只保存在 PostgreSQL 和宿主机的图片目录中。图片目录默认是 Compose 文件旁的 `./data/storage`，可通过 `STORAGE_HOST_PATH` 指定其他宿主机路径。Redis 开启 AOF，承载 Celery broker；数据库事务通过 Outbox 投递任务，因此 Redis 暂时不可用时不会丢失已提交的业务任务。

## 启动

1. 生成配置：

```bash
cp .env.example .env
mkdir -p data/storage
openssl rand -hex 32       # 分别填写 SECRET_KEY、JWT_SECRET_KEY、TRAINING_WORKER_TOKEN
openssl rand -base64 32    # 填写 ENCRYPTION_KEY
```

2. 编辑 `.env`，至少替换所有 `replace-with-...` 值，然后启动：

```bash
docker compose up --build -d
```

Compose 会先运行 `alembic upgrade head`，迁移成功后才启动 API、Outbox dispatcher、生成 worker、媒体 worker、维护任务和前端。应用不会在启动时执行 `create_all` 或隐式 schema 修补。

3. 创建首个管理员：

```bash
docker compose run --rm backend flask --app manage.py create-admin \
  --username your-admin --password 'replace-with-a-strong-password'
```

4. 打开 `http://localhost:4173`。生产 HTTPS 部署必须设置 `FRONTEND_URL=https://...` 和 `REFRESH_COOKIE_SECURE=true`。

独立 GPU 主机使用 `docker-compose.trainer.yml` 启动 trainer。trainer 会按
`TRAINER_HEARTBEAT_INTERVAL_SECONDS`（默认 15 秒）主动向平台保活；Forge 的“训练节点”页面会展示已注册节点、忙闲状态和最近心跳。平台默认在 60 秒未收到心跳后将节点标记为离线，可通过 `TRAINING_WORKER_OFFLINE_SECONDS` 调整。

trainer 注册时会通过能力信息上报可训练模型，训练页面据此提供模型选择并把任务只分配给兼容节点。默认上报 YOLOv8 和 YOLO11 的 n/s/m/l/x 型号；可用逗号分隔的 `TRAINER_SUPPORTED_MODELS` 覆盖该列表。

模型管理会使用已加密保存的 Gemini API Key 获取当前账号可见、且生成客户端兼容的图像模型，并缓存 15 分钟；可通过 `PROVIDER_MODEL_CACHE_TTL_SECONDS` 调整缓存时间。供应商不可达或不支持模型发现时会回退到内置兼容目录，模型 ID 仍可手动输入。即梦推理 API Key 无法调用火山方舟控制面模型列表，因此当前使用内置目录。

### 可选的智能点选

标注工作台可使用 SAM 2.1 small 将正点/排除点生成临时 mask，人工确认后只保存现有矩形框，不改变训练和导出格式。启用同机 GPU 服务时，先为 `SEGMENTER_SHARED_TOKEN` 生成至少 32 位随机值，并设置：

```dotenv
SEGMENTER_URL=http://segmenter:8100
SEGMENTER_SHARED_TOKEN=replace-with-at-least-32-random-characters
```

然后启动可选 profile：

```bash
docker compose --profile segmentation up --build -d
```

该 profile 需要 NVIDIA Container Toolkit 和一块可用 GPU。模型源码固定到 Dockerfile 中的 SAM 2 commit，SAM 2.1 small 权重在镜像构建阶段从 Meta 的版本化地址下载并校验 SHA-256；生产启动不会联网下载。独立 GPU 主机可运行 `docker compose -f docker-compose.segmenter.yml up -d`，将同一令牌配置到两端，按需把 `SEGMENTER_BIND_ADDRESS` 改为 GPU 主机的内网地址，并把平台的 `SEGMENTER_URL` 指向该地址。不要把 8100 端口暴露到公网。未配置 URL 时，前端不显示智能点选入口，手动画框保持可用。

## 开发与测试

```bash
cd backend && pip install -r requirements.txt
cd backend && PYTHONPATH=. pytest
cd annotator && PYTHONPATH=. pytest
cd segmenter && PYTHONPATH=. pytest
cd trainer && PYTHONPATH=. pytest
cd frontend && npm ci && npm run build
```

测试使用 SQLite 内存库以获得快速反馈；CI 额外使用真实 PostgreSQL 执行 Alembic upgrade、`alembic check`、downgrade 和再次 upgrade。

## 数据库与迁移

- 生产数据库固定使用 PostgreSQL；UUID、JSONB、数值精度、外键、唯一约束和检查约束由数据库保证。
- `20260717_01` 支持空库初始化和旧 Compose PostgreSQL 库接管；当前 head `20260721_01` 增加增强源图谱系。旧 SQLite 文件仍不支持原地迁移到 PostgreSQL，需使用导入流程。
- 修改模型后必须生成并审阅迁移，再运行：

```bash
cd backend
alembic upgrade head
alembic check
```

## 认证

- 登录前必须获取图片验证码。验证码默认 5 位、120 秒有效、绑定请求客户端且只能消费一次；长度和有效期可通过 `LOGIN_CAPTCHA_LENGTH`、`LOGIN_CAPTCHA_EXPIRES_SECONDS` 调整。
- Access token 默认 15 分钟，只保存在前端内存中。
- 刷新令牌是可撤销、轮换的 opaque token，仅存于 `HttpOnly`、`SameSite=Lax` Cookie；同一客户端的并发轮换有默认 10 秒宽限期，宽限期外检测到旧 token 复用会撤销整个 session family。
- 页面刷新时前端先进入“检查中”状态，通过 refresh cookie 恢复用户和新的 access token；确认失败后才进入登录页。登录成功后会返回原先访问的站内页面。
- 浏览器携带 refresh cookie 的请求会校验 `Origin`：接受配置的 `FRONTEND_URL`，也接受反向代理转发的当前同源 host。HTTPS 部署必须让代理保留原始 `Host` 和 `X-Forwarded-Proto`。
- 生产默认 `REGISTRATION_MODE=disabled`，首个账户通过 CLI 创建。
- Nginx 对验证码、登录和注册接口分别限流。外部部署还应在 CDN/WAF 层增加 IP 与账号维度规则。

当前系统的授权模型是“登录用户 + 数据归属隔离”：业务 API 必须携带 access token，数据集、图片、模型配置和外部连接按 `user_id` 查询；`plan` 只是套餐展示字段，不是角色或管理员权限。以后如需多人管理员/只读角色，应单独增加 role/permission 模型，不要复用 `plan`。

## 文件与任务

- 所有图片、视频源、导出包、训练产物和推理输入都登记在 `assets` 表，并通过原子临时文件替换写入。
- 前端不能直接访问存储 volume；鉴权通过后，Flask 返回 `X-Accel-Redirect`，由 Nginx 内部 location 发送文件。
- 删除图片先写 Asset tombstone，维护服务在保留期后清理文件。
- 生成、增强和视频任务使用 TaskItem 租约确保单执行者；软时限退出会释放租约并由 Celery 重排队续跑。训练/推理任务使用数据库原子领取、assignment token 和可续期租约。
- 关键创建接口支持 `Idempotency-Key`；同一个 key 与同一请求会回放首个结果，key 被不同请求复用会返回 409。

## 监控端点

- `GET /api/v1/health/live`：进程存活
- `GET /api/v1/health/ready`：PostgreSQL、Redis、存储就绪
- `GET /metrics`：Prometheus 指标（仅后端容器网络暴露）

所有 API 响应包含 `X-Request-ID`，应用日志为 JSON。Docker 日志默认限制为 20 MB × 5 个文件。

## 备份

```bash
BACKUP_ROOT=/safe/off-host/path scripts/backup.sh
scripts/verify-backup.sh /safe/off-host/path/<timestamp>
RESTORE_CONFIRM=dataset-gen scripts/restore.sh /safe/off-host/path/<timestamp>
```

建议每天执行一次并复制到异机/对象存储，对应 RPO 24 小时；每月至少做一次隔离恢复演练，以验证 RTO 4 小时目标。
