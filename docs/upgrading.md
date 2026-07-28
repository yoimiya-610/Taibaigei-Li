# 升级与回滚

## v0.7.0 / 公开基线 v0.7.0.1

从该基线起，`yoimiya-610/Taibaigei-Li` 是公开产品的上游源仓库。包版本统一为 v0.7.0；v0.7.0.1 是本次公开基线工作的标识，不创建正式 GitHub Release。

升级前先检查当前 checkout：

```bash
git remote get-url origin
git status --short
```

如果 `origin` 不是下面的公开仓库，请不要在原目录改写远端或拼接历史；在新目录创建独立 clone，再迁移运行状态。

```text
https://github.com/yoimiya-610/Taibaigei-Li.git
```

## 备份运行状态

先停止 NoneBot，再在仓库根目录创建仓库外快照：

```bash
state_dir="../taibaigei-state-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$state_dir"
[ -d mybot/data ] && cp -a mybot/data "$state_dir/"
[ -d mybot/logs ] && cp -a mybot/logs "$state_dir/"
[ -d backups ] && cp -a backups "$state_dir/"
cp mybot/.env "$state_dir/env" 2>/dev/null || true
```

快照可能包含密钥、用户 ID 和消息内容，不得提交或上传到公开 PR。

## 公开仓库原有部署

确认工作区无本地代码修改后：

```bash
git fetch --prune origin main
git merge --ff-only origin/main
uv sync --project mybot --locked
uv run --project mybot python tools/check_public_tree.py
uv run --project mybot python -m unittest discover -s mybot/tests -v
```

随后按 [部署指南](deployment.md) 启动并验证 OneBot 连接。

## 从其他 checkout 迁移

1. 保留旧目录，不修改其 Git 历史或远端。
2. 在新目录 clone 公开仓库。
3. 从快照复制 `.env` 和运行目录到新 checkout。
4. 执行锁定依赖同步、测试和启动检查。
5. 确认新实例稳定后再停止使用旧目录。

示例恢复命令需在新仓库根目录执行：

```bash
cp "$state_dir/env" mybot/.env
[ -d "$state_dir/data" ] && cp -a "$state_dir/data" mybot/
[ -d "$state_dir/logs" ] && cp -a "$state_dir/logs" mybot/
[ -d "$state_dir/backups" ] && cp -a "$state_dir/backups" .
```

## 数据兼容性

v0.7.0 保持既有 JSON 状态兼容，并可能按使用情况新增：

- 群级功能开关的 `groups` 字段。
- 群聊记录目录与 YAML 日志。
- 太白酒馆、翻译和实用工具相关状态。
- 新历史小游戏的功能键和轮换信息。

没有强制的一次性数据迁移。旧版本通常会忽略未知字段，但不会理解新功能产生的全部状态。回滚前应先停止写入、备份当前状态，并关闭只存在于新版本的功能。

## 回滚

1. 停止 NoneBot。
2. 记录当前提交和失败现象。
3. 切换到已验证的旧提交或旧部署目录。
4. 恢复升级前的数据快照。
5. 执行该版本对应的锁定依赖同步并启动验证。

不要使用会删除未跟踪文件的清理命令处理部署目录；运行数据本来就不受 Git 管理。代码回滚和数据回滚应分别执行，以便保留诊断与恢复空间。
