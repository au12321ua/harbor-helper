# 独立有界验收：automation API v1

## 判定

**限定 PASS**，仅适用于下列固定候选与实际检查范围；不代表全套回归、真实外部执行或生产部署验收。

- 候选：`50b0dde46d66bd509fed3fe56eb749919779968c` (`origin/feature/automation-api-v1`)
- 初始现场核对：cwd `/home/pc/auua/projects/cad/harbor-helper`，HEAD `9451363155674f138123c94c5e1ba51687139b36`；`origin/dev` 仍 `28102da4`，`master`/`origin/master` 仍 `94513631`。
- 使用 detached worktree `/tmp/hh-checker-automation-v1-50b0dde`。工程树 `/tmp/hh-automation-api-v1` 只读取证。源代码/static 与修正提交 `bad020357104dc72bed7c955ae5dc16d0c2e104f` 一致，50b0 候选在该修正提交上只增加报告/日志归档文档；工程报告两份正文在工程树与候选间 SHA256 相同。

## 本轮独立检查

- 复核两份工程报告与日志索引；索引列出的 18 份日志 SHA256 和字节数全部匹配。没有把旧 `d46e31a` 上的 292 Python/28 UI，或 `bad0203` 上报告的 52 Python/1 UI，倒算作 50b0 的独立通过。
- 在 `env -i` 与本轮独立 HOME 下运行；pytest 为每例创建临时 state/master/Profile。Python 依赖从工程树既有 `.venv` 只读复用，前端 node_modules 只读复用后移除临时 symlink；候选源码从独立 worktree 加载。`tests/test_automation.py tests/test_automation_http.py tests/test_service_cli.py`，**54 passed**，有 1 条 Starlette/httpx 弃用提示。覆盖凭证密码复核、一次性原值/摘要/默认 read、scope 与管理员 PAT 边界、撤销/过期/停用/重置；固定操作幂等、跨同成员 PAT/网页恢复、目标冲突、旧键兼容及当前访问身份；三轴、安全报告/schema/discovery/error；修正后的非对象 JSON RemoteError、action 类型/长度/脱敏及严格未来到期（NaN/inf/bool 拒绝、730 天接受）。
- 实际监听 HTTP→生产 scheduler/worker 流程通过：CLI 发现、提交、同键恢复、附件版本、查询与安全零分报告；source/worker 执行 adapter 位于 harness 复制包内的隔离 fixture，不是真实 Harbor/Docker/Hub/模型执行。凭证原值未出现在 profile 输出、worker/产物/日志断言中。
- 生产构建静态页真实 HTTP + Playwright 浏览器路径通过：错误密码保留会话并清空密码；默认只读凭证签发仅一次呈现，关闭并重载后无法找回；撤销生效。首次尝试因隔离 worktree 缺 Node 依赖而未启动页面；配置只读复用依赖与 Node 22 后，完整专项重跑 54 项通过。已将通过用例截图保存在 `evidence/credential-ui.png`；截图在关闭原值并撤销后取得，不包含原值。测试生成的隔离 state/master 与专属 pytest 临时目录已清理；报告和截图保留。
- 自建合成旧 schema state：删除仅本候选新增的两表后重新打开；`access_credentials`、`access_events` 被创建，原表 DDL、用户和加密凭据行不变，旧凭据仍可解密，state 外 master 的内容摘要/权限保持不变。此为合成迁移检查，不是正式 state 升级演练。

## 未覆盖与边界

- 未重跑全量 Python/UI、build/lint；这些仅作为各报告固定版本的历史记录，且对应对象不同。未运行 Docker、Hub、Oracle 或模型请求；没有改部署树、正式 state/master、dev/master 或集成分支。
- 未作生产升级/恢复、外部 HTTPS/代理、真实数据集/镜像可执行性或全系统安全审计。
- 检查结论基于固定候选与当前 Linux/Python 3.13/Node 22 环境；隔离 fixture 的执行成功不能推论真实外部执行成功。
