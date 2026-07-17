# 运维手册

## 发布流程

1. 在 CI 通过 Python 测试、前端构建、真实 PostgreSQL 迁移校验和镜像构建。
2. 发布前运行 `scripts/backup.sh`，并将备份复制到宿主机之外。
3. 拉取按 commit SHA 标记的镜像，不使用不可追溯的临时 tag。
4. `docker compose run --rm migrate`。
5. `docker compose up -d`，检查 `/api/v1/health/ready` 和错误率。

迁移必须向后兼容当前应用版本。破坏性字段删除采用 expand/contract：先加新字段并双写，回填和验证后，再在后续版本删旧字段。

## 回滚

- 应用错误且 schema 兼容：将 `BACKEND_IMAGE` / `FRONTEND_IMAGE` 指回上一 commit SHA，再 `docker compose up -d`。
- 迁移错误且尚未写入新格式数据：使用经审阅的 `alembic downgrade <revision>`。
- 已产生不兼容数据：停止写入，使用最近验证备份恢复。不要盲目执行 downgrade。

## 备份策略

- 每日：PostgreSQL custom dump + `STORAGE_HOST_PATH` 图片目录 tar + SHA-256 清单。
- 保留：建议 7 个日备份、4 个周备份、3 个月备份。
- 异地：备份完成后复制到独立对象存储或另一主机。
- 演练：每月在隔离环境执行 restore，登录并抽查数据集、图片、标注和导出。

脚本默认目标是 RPO 24h / RTO 4h。若业务不能接受 24h 数据丢失，应增加 WAL 归档/PITR 和更高频的存储增量备份。

## 告警建议

- readiness 连续 3 分钟失败。
- API 5xx 比例 5 分钟超过 2%。
- P95 请求延迟 10 分钟超过 2 秒（上传/下载路由单独统计）。
- Outbox 最老未发布事件超过 2 分钟。
- Celery 队列长度持续增长 10 分钟。
- PostgreSQL 磁盘超过 75%，宿主机图片目录所在磁盘超过 80%。
- 训练任务租约反复过期或单任务 attempt count 超过 3。
- 最近一次成功备份超过 26 小时。

## 常见故障

### Redis 不可用

API 事务仍会把任务写入 Outbox。恢复 Redis 后 dispatcher 自动继续发送。不要手工把 running 任务批量改成 completed。

### Worker 异常退出

TaskItem 或训练 assignment 租约到期后允许其他 worker 恢复。检查原任务的唯一约束冲突和 attempt count；重复消息本身不是数据损坏。

### 存储不足

先暂停导入/生成 worker，扩容或转移 `STORAGE_HOST_PATH` 目录；运行 `flask --app manage.py gc-assets --retention-hours 0` 只会清理已写 tombstone 的文件，不会删除活跃 Asset。

### 数据库连接耗尽

检查长事务和慢查询，再调整 `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW`。总连接上限约为 API 进程、worker 进程和维护进程各自连接池之和，不能只看单服务配置。

### 刷新页面后回到登录页

先检查浏览器中 `/api/v1/auth/refresh` 的响应。`401` 通常表示 refresh cookie 缺失、过期或已撤销；`403 untrusted origin` 表示外部访问地址与 `FRONTEND_URL`/代理转发信息不一致。确认：

- `FRONTEND_URL` 使用浏览器实际访问的协议、域名和端口；多个来源用逗号分隔。
- HTTPS 环境设置 `REFRESH_COOKIE_SECURE=true`。
- 最外层代理保留原始 `Host`，把原始 `X-Forwarded-Proto` 继续传给前端 Nginx，且没有改写 `Set-Cookie` 的 Path。
- 前端与 API 跨站部署时不要继续使用默认 `SameSite=Lax` 方案，应改为同站域名或单独设计 `SameSite=None; Secure` 和更严格的 CSRF 防护。
