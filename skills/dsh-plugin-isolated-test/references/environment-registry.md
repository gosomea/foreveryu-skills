# 隔离环境登记与复用

使用 skill 自带的 `scripts/environments.py` 管理部署记录。脚本只依赖 Python 3.9+ 标准库，使用 SQLite，无需安装服务。进程核验使用 macOS/Linux 的 `ps`，完整 cwd/端口核验还需要 `lsof`；无法读取的状态会显示 `unknown`，不会推断为通过。

## 数据存在哪里

默认数据库：`~/.local/state/dsh-plugin-isolated-test/environments.sqlite3`；设置了 `XDG_STATE_HOME` 时使用其对应目录，也可通过全局 `--db <path>` 显式指定。数据库在本机持久化，独立于会话、Git checkout 和 TMP 目录。不同对话使用同一默认路径才能互相发现。不要为每个对话另设数据库，也不要将数据库提交到 Git。

数据库文件权限为 `0600`。记录项目、用途、源码目录、插件目录、`DSH_HOME`、profile、无认证参数的 URL、PID 与进程指纹、进程管理器名称、私有日志路径、接续说明，以及多个用例的工作区和 Session ID。日志内容、认证 token、API key 不入库。SQLite 事务串行化登记操作，同一个 home 不能重复登记；同项目新增环境必须说明原因。它不锁定实际 Host，因此多 Agent 同时修改部署仍需先协调。

## 先查，后复用

以下 `DSH_ENV_SCRIPT` 应设置为当前 skill 目录下脚本的绝对路径；`DSH_PLUGIN_PROJECT` 使用稳定的插件项目目录，同一项目的不同构建副本共用该值。

```bash
python3 "$DSH_ENV_SCRIPT" list --project "$DSH_PLUGIN_PROJECT"
python3 "$DSH_ENV_SCRIPT" show supervisor-user
python3 "$DSH_ENV_SCRIPT" check supervisor-user
```

- `list` 给出简洁候选列表，首选部署排在前面；`show` 展开接续说明和用例对应关系。
- `check` 只读取本机目录及进程状态；同时核对 PID 指纹、cwd、`DSH_HOME`、profile 和监听端口。`live_identity_verified: true` 只说明 Host 身份核验通过，不能代替模型请求、插件就绪、构建兼容性和任务空闲检查。命令退出 0 只说明检查成功执行，要读取 JSON 中的结论。
- `retained` 表示应保留供用户验收或复现，仍可在兼容情况下复用；`active` 表示当前部署，`retired` 表示不再作为复用候选。这是登记状态，不是实时进程状态。
- 目录仍在但进程退出时，先检查已知启动方式和任务恢复要求，再决定重启原隔离 Host；不要因为进程退出就另开一套环境。
- TMP 目录已被系统清理时，保留旧记录供追溯，确认后将旧部署标记为 `retired`，创建并登记替代部署。不要凭陈旧 PID 或端口停止进程。

如果用户提供了已有 URL，而登记为空，先核实该 URL 对应的 PID、cwd、home、profile、插件链接和用途，登记后复用；不能把“未登记”理解成“没有环境”。

## 登记部署

先分配目录，再立即登记，即使 Host 尚未启动；此时省略 PID/URL。这样下一次对话可发现正在准备的部署。已有部署迁入记录时可一次填入已核实的 PID/URL：

```bash
python3 "$DSH_ENV_SCRIPT" register supervisor-user \
  --project "$DSH_PLUGIN_PROJECT" \
  --source "$DSH_SOURCE" --plugin "$DSH_PLUGIN" \
  --home "$DSH_TEST_HOME" --profile "$DSH_TEST_PROFILE" \
  --purpose 'Supervisor 中文任务与人工验收' --preferred \
  --state retained --note '用户仍在验证；修改构建或重启前先核查活动任务'

python3 "$DSH_ENV_SCRIPT" update supervisor-user \
  --pid "$DSH_TEST_PID" --url "http://127.0.0.1:$DSH_TEST_PORT" \
  --supervisor "$DSH_TEST_SERVICE" --log "$DSH_TEST_LOG"
```

`register` 创建新 ID，不覆盖旧记录。`update` 修改用途、说明、状态、首选项，以及重启后的 PID/URL 或确认后的 source/plugin/profile。`home` 和项目身份固定，搬迁 home 应建立新记录。日志路径可用于私下找到完整 Web 启动认证链接；登记中的裸 URL 本身不能为新浏览器完成登录。

同项目确需不同构建或并行隔离时，在第二次 `register` 提供 `--reason '现有环境供用户验收，当前构建与之不兼容'`。首选项是每个项目唯一的发现提示，不能绕过活动任务和构建兼容性检查。优先复用 Host/home；若仅用例需要空目录，在该部署下新建 TMP 工作区即可。

## 登记用例与交接

先通过 DSH 原生接口创建／绑定 Session，再把事实登记进 SQLite：

```bash
python3 "$DSH_ENV_SCRIPT" bind supervisor-user \
  --case chinese-approval --workspace "$DSH_TEST_WORKSPACE" \
  --session "$DSH_TEST_SESSION" --purpose '中文计划、文字批准、独立审查'

python3 "$DSH_ENV_SCRIPT" update supervisor-user --state retained \
  --note '中文批准已通过；接下来验证暂停恢复。保留当前 Session 供用户检查。'
```

`bind` 只登记，不替代 DSH 的 Session 绑定；同一个 case ID 会更新原记录。需要保留多次运行时使用不同 case ID。尚未创建 Session 的准备目录可以省略 `--session`，创建后再补齐。说明记录当前任务、已验证事项、下一步和保留原因，不记录敏感内容。

脚本不会自动启动、重启、杀进程、修改 profile 或删除目录。后续清理仍按 skill 的宿主身份、活动任务及产物检查规则执行，清理后更新登记状态。
