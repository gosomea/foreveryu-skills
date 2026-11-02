# DSH 插件隔离测试 Runbook

需要安装隔离 profile、执行真实宿主测试，或测试下文的 reviewer 示例时读取本页。变量名都是示例；先解析为当前机器上的绝对路径，不要直接照抄路径或端口。§5–8 的 judge、observe、dispatch、evidence 断言是 **JEV 类 post-turn reviewer 插件的案例**，其他插件应换成自己的行为断言。

## 1. 建立测试变量与基线

先按[隔离环境登记流程](environment-registry.md)查询当前项目的已有部署，并核实 Host 身份、测试用途和用户验收状态。一个部署可以承载多个工作区与 Session；新用例不等于新建一套 Host。下面的变量优先从登记记录中读取，仅在确实需要新部署时另行分配。

使用任务专用变量，不要重用 `HOME`、`CODEX_HOME` 等系统变量：

```bash
DSH_SOURCE=/absolute/path/to/deepseek-harness
DSH_PLUGIN=/absolute/path/to/plugin
DSH_TEST_HOME=/absolute/path/to/.dsh-plugin-smoke
DSH_TEST_PROFILE=plugin-smoke
DSH_TEST_PORT=3101
DSH_TEST_TEMPLATE=web
DSH_NODE=/absolute/path/to/a-supported-node
```

确认 Node 和两套 CLI 的版本。若 global CLI 与 checkout 不同，以 checkout 为准：

```bash
"$DSH_NODE" --version
dsh --version
cd "$DSH_SOURCE"
"$DSH_NODE" --import tsx/esm apps/cli/src/bin.ts --version
```

先找到**实际**日常实例，确认 PID、命令、cwd、启动它的 DSH_HOME 和监听端口（如有）。下面只演示发现过程；`3080` 和 `~/.dsh` 不是默认结论：

```bash
lsof -nP -iTCP -sTCP:LISTEN | rg 'dsh|node'
# 核实后设置 DSH_DAILY_PID 和 DSH_DAILY_HOME，再运行下面两条。
ps -p "$DSH_DAILY_PID" -o pid=,ppid=,command=
find "$DSH_DAILY_HOME/sessions" -type f -name 'session.v3.jsonl.zstd' -exec stat -f '%m %N' {} +  # macOS: mtime + path
git -C "$DSH_PLUGIN" status --short
```

如果将重建 DSH 本体，先按 `knowledge/Agent工程/框架源码/DSH/dsh-isolated-source-instance.md` 克隆 checkout、克隆 `DSH_HOME`、重指 profile 的 checkout 内 `link:`，再继续。插件本身的绝对 `link:` 可继续指向待测插件目录。

## Prepare the test workspace

先查看部署登记中的 cases，同一用例优先复用兼容工作区；需要全新 fixture 时，由 Agent 在系统 TMP 目录新建工作区，自动完成测试 Session 的绑定。工作区独立于 DSH 源码、插件源码和隔离 `DSH_HOME`；复用时先确认其中没有其他任务的产物。下面用平台临时目录 API 创建唯一目录，并取得规范化绝对路径：

```bash
DSH_TEST_WORKSPACE="$(python3 - <<'PY'
import pathlib
import tempfile
print(pathlib.Path(tempfile.mkdtemp(prefix="dsh-plugin-workspace-")).resolve())
PY
)"
export DSH_TEST_WORKSPACE
```

1. 按用例写入最少的 fixture；需要 Git 行为时再初始化测试仓库。不要复制其他测试任务的 README、验收脚本或指令，以免影响本次模型任务。
2. 从当前 checkout 的文档或源码核实创建／绑定 Session 的 CLI、SDK 或 Host API，显式传入 `DSH_TEST_WORKSPACE`。不同版本的参数和接口可能变化，不能猜测 `--cwd` 等参数，也不能直接修改内部 Session 存储冒充正式创建流程。
3. 读取 Host 返回的 Session 元数据或持久化记录，确认实际工作目录与该路径一致；涉及子 Agent 时核实其工作目录符合用例预期。仅 `mkdir`、Host 的启动 cwd 或网页显示了目录名，都不算完成绑定验证。
4. 在绑定完成后执行任务。需要浏览器验收时，直接打开准备好的 Session，检查真实交互和状态；交给用户验证时提供可用的 Session，并记录其工作区绝对路径。

常规测试不需要逐级点击网页目录选择器，也不需要让用户选工作区。只有用例必须读取已有项目或文件时，才使用对应已有目录，并优先为写入测试准备可丢弃副本。目录选择器本身就是测试目标时单独验证它；若目标版本确无可用的直接绑定接口，可以使用选择器兜底，并在报告中说明原因。

通过登记脚本的 `bind` 记录临时工作区、测试 home 和 Session ID 的对应关系。用户还要验证、任务仍在运行或需要复现时保留工作区，并用 `update --state retained --note ...` 留下接续说明；测试结束后按已有清理规则处理。不要把临时路径提交为项目的固定配置。

## 2. 插件自身验证

优先使用项目声明的脚本，例如：

```bash
cd "$DSH_PLUGIN"
pnpm run verify  # 仅当 package.json 声明了 verify；否则运行其实际 check/test/build 脚本
pnpm pack --dry-run
```

检查 pack 清单与 `package.json` 的 `main`、`exports`、`types`、`dsh.bundle.patch` 等**实际声明**一致。若声明了类型或 bundle patch，相关文件必须打包；没有声明就不要凭通用模板强制要求。不得包含密钥、会话、日志或临时 profile。

若插件调用真实外部判断服务，先用合成状态跑最小 API smoke。只输出模型、结构化分数、usage 和选择结果；不要打印 request headers 或 API key。

## 3. 初始化隔离 profile

选择与测试目标一致的模板：纯配置/一次性主流程可用 `headless`；异步 post-turn sidecar 用 `web` 或 `tui`。

```bash
mkdir -p "$DSH_TEST_HOME"
export DSH_HOME="$DSH_TEST_HOME"
cd "$DSH_SOURCE"

"$DSH_NODE" --import tsx/esm apps/cli/src/bin.ts \
  --profile "$DSH_TEST_PROFILE" \
  --from-default-profile "$DSH_TEST_TEMPLATE" \
  --dump-config >/tmp/dsh-plugin-smoke-initial.yml

"$DSH_NODE" --import tsx/esm apps/cli/src/bin.ts \
  plugin --profile "$DSH_TEST_PROFILE" \
  add "link:$DSH_PLUGIN"
```

若命令退出 `0` 却既无输出又未修改 profile manifest，先查 Node engine。Node 23 下的 source `bin.ts` 可能因 `import.meta.main` 未触发而成为空操作；换成 Node 24 后原命令重试，不要手改 manifest 来掩盖启动器问题。

## 4. 验证配置合成（层 4，**不需要起宿主**）

`--dump-config` 由启动器直接打印合成结果，不监听端口、不挂载插件，也不求值 `!!js`。
它能在启动宿主前回答「插件配置行是否存在且被启用」；不能证明模块加载、service 注入或运行状态。

> 捷径与其代价：把插件 `symlink` 进 `$DSH_HOME/profiles/<p>/node_modules` 再挂 `--patch`
> overlay 也能跑起来，但那验证的是「Node 能解析到这个包」，**不是**「插件能通过受支持
> 路径安装并合成」。后者才是发布前提。用 `dsh plugin add link:<abs>` 走正式路径，再用
> 本节的 `--dump-config` 证明 plugin row 已进入合成配置。

```bash
"$DSH_NODE" --import tsx/esm apps/cli/src/bin.ts \
  --profile "$DSH_TEST_PROFILE" --dump-config \
  | rg -n -C 6 'actual-plugin-id|actual-package-name'
```

同时检查 profile manifest：

```bash
rg -n 'actual-package-name|bundles' \
  "$DSH_TEST_HOME/profiles/$DSH_TEST_PROFILE/package.json"
```

必须区分：

- 包已在 `dependencies`：pnpm 能解析它；
- 包已在 profile `bundles`：它的 bundle patch 会参与合成；
- dump 中有启用的 plugin row：Cordis 启动时才会尝试激活它；
- 实际 module 加载、service/provider 可用和注入成功：**下一层启动宿主后**检查，不能从 dump 推出。

## Reuse the daily model configuration

需要真实模型调用时，先确认日常 Host 实际使用的 provider、model、推理设置和提供方连接配置，再在**隔离 Host 的 profile 或 settings** 中复用这些模型配置。只复制所需模型配置，不把整个日常 profile 或 `$DSH_HOME` 作为测试目录。日常配置与隔离配置的路由应一致；如果插件允许审查者另选模型，也记录主 Agent 与审查者各自实际使用的路由。

日常 Host 的 `agent-default-model` 通常指向所配 LLM provider 的**第一个模型**。先记录这条路由的四要素：`provider`、`model`、`api` 适配器与 `baseURL`、以及凭据引用名（`apiKeyEnv`）。注意 provider 别名与凭据环境变量名可能拼写不同，二者不能混用；同一厂商若有多条代理路由（不同 baseURL 或路径），务必复制日常 Host 实际使用的那一条。每轮先重新读取日常有效配置，再将对应提供商配置和 `agent-default-model` 行复制到隔离 profile。

分别用两套 `DSH_HOME` 运行 `--dump-config`，核对两侧 `agent-default-model.provider` 与 `model` 一致（model 等于该提供商模型列表的第一项），并核对 `api`、`baseURL` 和 `apiKeyEnv`。日常实例若已运行，还需验证运行态是否已加载新默认值；配置文件与 dump 一致不能代替运行态检查。不要为修改日常默认值而擅自重启有工作中的日常 Host。

凭据与模型路由是两层：隔离 `DSH_HOME` 不会自动读取日常 home 的 `.credentials.yaml`。为隔离 Host 的启动环境安全提供对应密钥，或在隔离 home 的 Models 页面／凭据存储中配置它。不要把密钥写进 patch、命令参数或日志，不要把隔离凭据文件软链接到日常的可写文件。若隔离 Host 尚无可用凭据，应先补齐，再进行真实模型测试；否则只能把该层记为**未测试**，不能用无凭据的 UI 冒烟测试代替。

`--dump-config` 只能确认配置已合成。启动隔离 Host 后发起一次最小真实请求，核对实际 provider/model、成功响应及新 Session 落在测试 home，再运行插件用例。模型配置不一致、请求未成功，或审查者未实际调用目标模型，都不能算真实模型验证通过。

## 5. 宿主 smoke；以下用 JEV 类 observe 插件举例

没有 post-turn / 派发路径的插件，也要验证其实际宿主行为：例如工具注册与调用、存储读写，或客户端插件所需的宿主路由。客户端页面的交互和数据断言再放到层 6。

一般插件应使用自己的事件、工具、服务或 UI 挂载断言。对提供 `mode: observe` 的 reviewer 插件，先保持生产阈值；如果它调用外部 judge，启动前检查**实际需要的**密钥是否存在，但不打印值。例如：

以下 `REVIEW_PROVIDER_KEY` 是占位名，运行前替换成插件实际读取的环境变量。

```bash
if [[ -n "${REVIEW_PROVIDER_KEY:-}" ]]; then
  echo 'REVIEW_PROVIDER_KEY=present'
else
  echo 'REVIEW_PROVIDER_KEY=missing'
  exit 1
fi
```

优先前台启动：

```bash
cd "$DSH_SOURCE"
export DSH_HOME="$DSH_TEST_HOME"
exec "$DSH_NODE" --import tsx/esm apps/cli/src/bin.ts \
  --profile "$DSH_TEST_PROFILE" \
  --patch ./apps/web/tests/pin-browse-picker.overlay.yml \
  --no-open --port "$DSH_TEST_PORT"
```

仅测试 Web 且需要页内目录选择器时才加上面这个随 checkout 提供的 `--patch`。其他宿主使用对应启动参数；TUI 等不监听的宿主无需端口。上述命令中 `--profile`、`--patch` 由 launcher 解析，`--no-open`、`--port` 交给 Web app。

如果必须后台运行 —— **stdin 是关键，`</dev/null` 在这里会杀掉服务**：

```bash
DSH_TEST_LOG="$DSH_TEST_HOME/run/web-$DSH_TEST_PORT.log"
umask 077  # 日志含启动认证链接，只允许当前用户读取
mkdir -p "$DSH_TEST_HOME/run"
touch "$DSH_TEST_LOG"
chmod 600 "$DSH_TEST_LOG"  # 也覆盖已有日志的权限
# stdin 必须永不 EOF：/dev/null 是可读且已结束的流，会让 app 在挂载后立刻退出。
sleep 31536000 | "$DSH_NODE" --import tsx/esm apps/cli/src/bin.ts \
  --profile "$DSH_TEST_PROFILE" \
  --patch ./apps/web/tests/pin-browse-picker.overlay.yml \
  --no-open --port "$DSH_TEST_PORT" \
  >>"$DSH_TEST_LOG" 2>&1 &
```

原因在 `packages/boot/cmdline/src/index.ts` 的 `exitOnStdinEnd`：它既监听 `end` 事件，也在挂载时检查
`stdin.readableEnded`。`/dev/null` 满足后者，于是**启动瞬间**就排队退出（实测约 4ms）。
对照实测：`/dev/null` → 4ms 退出；保持打开的管道 → 持续存活。杀掉持有 stdin 的进程会让实例立刻
`ECONNREFUSED`，而日常实例不受影响。

另外不要在服务后面接 `| grep`（读者消失时可能吃 SIGPIPE）。验证脱离与否时确认 fd `0` 保持打开且未到 EOF；`/dev/null` 是错的。若端口被一个被监管的实例反复占回，选择新端口，不要循环 kill。

### Web browser authentication

Web Host 启动后会打印 `dsh web: http://127.0.0.1:<port>/?token=...`；`--no-open` 只禁止自动打开浏览器，不禁止打印该链接。这个 token 属于当前进程。目标浏览器访问**完整启动链接**后，Host 设置绑定该 `host:port` 的 HttpOnly Cookie，并重定向到不带 token 的 `/`。之后同一浏览器配置中可以打开裸地址；新浏览器、独立浏览器配置或不同 `host:port` 没有这枚 Cookie，直接打开裸地址会收到 `dsh web authentication required; reopen the URL printed by dsh web.`。同一测试 home 的签名密钥通常能让已有 Cookie 跨 Host 重启继续有效，但旧启动 token 本身不能用于新进程。

把启动链接当作访问凭据：保留在受控终端输出，或保存在权限为 `0600`、位于隔离 home 的启动日志中；不要把 token 写进 Git、测试报告、共享日志或普通 Markdown 链接。交给用户查看页面时，在他们实际使用的浏览器里打开完整链接，并验证重定向后页面可见。只提供裸地址并不能给新浏览器完成认证。

如果启动输出被丢弃，先检查同一 authority 下是否已有可工作的已认证标签，尤其在后台整理任务运行时不要为了取得链接直接中断它。当前 CLI 没有从运行中的 Host 重新打印进程 token 的常规入口；确实需要给另一个浏览器登录时，先确认并保存异步任务进度，再只重启已识别的隔离 Host，捕获新的启动链接并恢复可续跑任务。不要复制 Cookie、签名密钥或绕过认证来补救。

在浏览器里提交一个安全、可审查但无真实破坏作用的 turn。Observe 验收重点不是“有一条 info 日志”，而是：

1. root session 持久化了标准 `turn/start ... turn/end`；
2. plugin 提取到的 turn 与 root turn 一致；
3. `userRequest` 只包含直接用户消息；
4. tool activity 只有工具名和成功/失败摘要，没有参数与结果正文；
5. secret pattern 被替换，字符预算生效；
6. 外部 judge 返回的字段被正确映射，失败时符合预定 fail-open/fail-closed 策略。

若 headless 只打印主 Agent 答案、看不到 Cordis `info`，不要立即判失败：headless 通常没有 stdout logger exporter。读取持久 Session 或提供测试专用 audit sink；不要把生产日志级别永久升高。

## 6. Dispatch smoke（仅适用于会派发子任务的插件）

使用单独的、明确标注为 smoke-only 的 overlay，不改默认 patch。若为了稳定触发而降低阈值，必须在注释和报告中说明，测试结束恢复生产阈值。

```yaml
# smoke-only: low thresholds force the real dispatch path
- id: verifier-plugin-id
  config:
    mode: dispatch
    provider: spawn
    model: jev-latest
    reviewThreshold: 0.20
    reviewerThreshold: 0.20
    maxEvidenceChars: 12000
    maxConcurrentTurns: 2
```

因为 row patch 会替换完整 `config`，不能只写 `mode: dispatch`。

启动持久宿主并提交一次测试 turn。`spawn` 验收时读取最近 Session header：

```bash
find "$DSH_TEST_HOME/sessions" \
  -type f -name 'session.v3.jsonl.zstd' -mmin -10 -print0 \
  | while IFS= read -r -d '' file; do
      (zstd -dc "$file" 2>/dev/null | head -n 1) || true
    done
```

至少确认：

- root session 的 `origin` 不是 `subagent`；
- child header 有 `origin: "subagent"`；
- `parentSession` 等于本次 root session id；
- `delegationDepth` 大于 `0`；
- child session 的 label/首条任务与预设 reviewer 对应；
- reviewer 最终产生了结果，plugin dispose 没有遗留运行任务；
- child `turn/end` 不再递归触发 reviewer。

文件数量从 N 增加到 N+K 只能提示发生了新会话，不能证明这些会话属于本轮 dispatch。

## 7. Post-turn headless 竞态

DSH headless runner 的典型顺序是：

```text
root agent.whenIdle()
→ flush root session
→ print result
→ request app exit
```

若 plugin 在 `turn/end` listener 里启动一个未被宿主追踪的异步 Promise，headless 可能在 judge 请求或 subagent 启动前退出。症状是：

- root turn 完整；
- 直接调用 judge 路由成功；
- dump-config 也正确；
- 但没有 child session，且进程很快正常退出。

这时用持久 Web/TUI 重测。若产品要求 headless 也保证 sidecar 完成，plugin 必须接入宿主可等待的 job/application-exit barrier；仅把 Promise 放进本地 `Set` 不会让 headless 的 `agent.whenIdle()` 等它。

## 8. Evidence 诊断

如果明显高风险的 turn 得分异常低，先比较证据长度与来源。DSH 会把以下内容持久化成 `user/message`：

- 人类直接消息：`source.kind === "user"`；
- system/runtime-context snapshot：`source.kind === "plugin"`；
- skills catalog：`source.kind === "skill-catalog"`；
- 其他插件注入。

把所有 `user/message` 无差别拼接会让几千字基础设施上下文淹没几十字用户意图。路由 evidence 通常只取直接用户消息；若业务确实需要某个插件上下文，则按允许列表显式加入，并单独计入字符预算。

同一条真实 Session 最好做两次对照：

1. 用插件 extraction 得到 evidence；
2. 把该 evidence 直接送给 judge 并打印结构化 plan。

这样能区分“宿主没有触发 listener”“证据提取错误”“judge 合理地选择 no review”和“dispatch provider 失败”。

## 9. 常见故障映射

| 现象 | 层 | 优先检查 |
| --- | --- | --- |
| 已提交的插件「源码」在仓库里其实是空的 | 2 | 全局 `lib/`、`dist/` 一类忽略规则会连带吞掉**无构建步骤**插件的源码；`git status` 仍然干净。用 `git ls-files <plugin>` 核对真实入库文件，必要时加 `!path/lib/` 否定规则 |
| plugin row 永远 pending | 4 | `inject` 的对象形式是「服务名 → intercept config」，**每个 key 仍是 required**，没有 optional 标记。`inject: {required:[...], optional:[...]}` 会让宿主编造两个叫 `required`/`optional` 的服务去等；可选服务用 `ctx.get(name)`，且不要写进 `inject` |
| 模型调用返回**空回复**而非报错 | 4/5 | 先确认 model id 在适配器 catalog 里：目录未注册的 id 会返回无内容的完成响应，而不是 typed error。用一次性路由把宿主自述的 `listProviders()` / `listModels()` 打出来核对，不要靠猜 |
| source CLI 退出 0 但无动作 | 4 | Node 23 / `import.meta.main`；换支持的 Node 24 |
| `cannot resolve profile bundle` | 4 | global CLI 比 checkout 旧 |
| credentials version/schema 报错 | 4 | 仍在用旧 CLI，不要先改凭证文件 |
| dump 中没有 plugin row | 4 | 装错 `DSH_HOME/profile`、bundle 未加入、patch 未打包 |
| Observe 终端没日志 | 5 | profile 没有 stdout logger exporter；查持久事件/测试 sink |
| 高风险 prompt 得分很低 | 5 | evidence 被 plugin/skill-catalog 消息稀释，或阈值/问题定义不合适 |
| headless 无 child | 5 | post-turn Promise 与 app exit 竞态 |
| key 在 shell 中存在但 host 报 missing | 5 | host 在设置 key 之前启动；重启隔离 host |
| 服务启动后退出 0 | 5 | **先查 stdin EOF**：后台用了 `</dev/null` 或 stdin 是已结束的管道 → app 挂载后立刻退出（见 §launch）。其次是日志管道 SIGPIPE、外层 job 结束 |
| kill 后端口又出现 | 5 | 进程受 supervisor 管理；换端口或通过 owner 停止 |
| 日常 Web 页面被重载 | 隔离 | 重建了日常实例正在服务的 checkout；需要源码克隆 |
| 裸地址显示 `dsh web authentication required` | 5/6 | 新浏览器没有该 `host:port` 的认证 Cookie。用本次 Host 打印的完整 `?token=` 链接登录；若启动行已丢失，按上面的 Web 认证步骤处理，勿把 401 当作插件页面故障 |
| 页面元素在但内容是空的 | 6 | 断言只查了「元素存在」。改为等待离开 loading 并记录网络响应状态；若组件自带数据则会误绿，补负向对照 |
| 点击超时，但 `force: true` 能过 | 6 | 通常仍有首屏 gate 覆盖：查 `[role="presentation"]` 数量。**不要**用 force 绕过——那正是要测的失败 |

## 9.5 客户端 UI 验证（层 6）

适用于贡献客户端界面的插件（注册导航行、主区域页面等）。本层要证明的是**页面渲染的是真实数据**，
而不仅是「页面上有东西」。

三个断言必须可证伪，缺一不可：

1. **可交互点击** —— 用普通点击，不要 `force: true`。`force` 会在首屏 modal 仍覆盖该行时也「成功」，
   恰好绕过你想测的失败模式。点击后必须出现 `aria-current="page"` 一类可观测的选中态。
2. **渲染 == 持久层** —— 把页面上渲染的行读出来，与**浏览器之外**独立读取的存储行对比。
   不要拿路由自己的响应当基准：那只能证明「前端复述了后端的话」，不能证明数据来自存储。
3. **负向对照** —— 阻断数据源（例如 `page.route(..., route => route.abort())`）后重新加载，
   在无缓存的全新浏览器上下文中要求页面呈现设计规定的空态/错误态，不得凭空出现源数据。
   若组件自带硬编码数据，这条会失败；若产品允许离线缓存，应另测其缓存行为，不能把缓存误判为硬编码。

配套注意：

- 首屏可能有**多个** gate（测试提示、缺少模型 key 等），每个都让 `#root` 保持 `inert`，
  从而拒绝普通点击。判定条件要同时满足「无 presentation overlay」与「root 不 inert」**连续两轮**，
  才能覆盖晚挂载的 gate。症状是点击超时且 `overlays: 1`。
- 数据路由若由插件的**宿主端**注册，先直接 `fetch` 该路由确认 200 与内容，再进浏览器。
  这样能把「宿主端没挂载」与「浏览器没渲染」分开。
- 页面用 `fetch` 取数时，等待它离开 loading 态再断言，并记下网络响应状态；
  只断言「元素存在」会把 404 误判成渲染失败。

## 10. 收尾与报告

结束前：

1. 停止带测试 overlay 的进程，并恢复插件原有安全配置；只有原本采用 `observe` 的插件才恢复为 `observe`；
2. 仅停止已确认 cwd、命令、端口和 `DSH_HOME` 的测试 PID；
3. 确认日常监听 PID 未变；
4. 比较日常与测试 home 的 session 变化；
5. 再跑插件 focused verify；
6. 检查 Git diff，确保没有日志、token、临时 profile 或 session 被纳入版本控制。

最终报告至少列出：执行命令、适用层的结果与独立证据、隔离证明、发现的问题，以及明确未覆盖的层。仅对使用外部 judge／子任务派发的插件补充 judge 模型版本、选择结果和 root/child session id（不含密钥）。
