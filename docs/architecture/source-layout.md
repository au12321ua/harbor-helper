# 源码职责

Python 位于 `src/harbor_helper/`；前端源码位于 `frontend/src/`，构建产物位于 Python 包根 `static/`。当前主干不保留旧路径转发层，历史源码路径按历史版本解释。

## 服务维护入口

| 责任 | 实现 |
| --- | --- |
| HTTP 装配、受保护启动、生命周期 | `service/api.py` |
| HTTP 安全边界与异常响应、实时依赖、SPA | `service/http/boundary.py`、`dependencies.py`、`spa.py` |
| 会话、自动化凭证、就绪、机器、实验、附件、管理路由 | `service/http/{session,access,status,machine,experiments,attachments,configuration}.py` |
| HTTP 输入、机器 DTO、浏览器 DTO、输出检查 | `service/http/inputs.py`、`dtos.py`、`browser_contracts.py`、`contract_boundary.py` |
| 自动化操作授权、角色与取消权限 | `service/policy.py`、`permissions.py` |
| 应用装配与目录组合 | `service/application.py` |
| 受理、幂等、继承与固定计划、取消 | `service/submissions.py`、`cancellation.py` |
| 安全报告、日志、产物、查询与用量 | `service/evidence.py`、`views.py` |
| ZIP 安全暂存与落盘、共享附件版本 | `service/bundles.py`、`attachments.py` |
| 初始化与持久能力装配 | `service/data.py`、`setup.py` |
| 账户会话、通用版本对象、加密凭据、容量、提交记录 | `service/data_{accounts,objects,credentials,capacity,submissionrecords}.py` |
| 提供商/模型配置、数据集/来源/作者参数业务 | `service/model_configuration.py`、`configuration.py` |
| 公共错误/输入校验/默认限额、密码策略 | `service/primitives.py`、`security/passwords.py` |
| 接纳资格与容量、只读调度观察、持久准备和保留维护 | `service/admission.py`、`observation.py`、`lifecycle.py` |
| 外部来源与 Docker 诊断 | `service/sources.py`、`docker.py` |

领域路由通过 `register(app, deps)` 直接注册在设有 `ContractRoute` 的 app 上。路由保持平铺，机器 schema、浏览器导出器和边界测试均从同一实际路由集合枚举。端点名同时是契约、授权和 HTTP 写审计的操作名，必须全局唯一。`policy.py` 完整定义能力表和机器 schema 操作集合，不在其他模块导入时增删。API 404 在最后的 SPA 兜底之前注册。

HTTP 依赖只保存 app、store 和认证依赖；业务数据每次从 `app.state.application` 取得。setup 和另一个进程完成初始化后，既有路由不捕获旧的空 application。API 关闭不停止队列和 worker。

`Application` 通过继承组合受理、取消与证据能力，构造一份数据、配置和附件依赖；方法只在所属能力类定义，不保留转发实现。证据、取消、包能力可只用 data 独立构造，受理需要 data、配置和附件；附件只取得 data 与包暂存能力。`ServiceData` 同样组合共用一个 store/root 的持久能力，初始化协调建表、引导与 PAT 表。通用对象存储只负责版本读写，不反向加载配置。

`model_configuration.Models` 是可独立构造的配置规则对象，显式接收对象读取、凭据元数据读取、版本持久化三个 callable；`ServiceData` 将 `Objects.object`、`Credentials.credential`、`Objects.save_version` 绑定为 `data.models` 的依赖，HTTP 通过 `data.models.save_object` 写入配置。模型规则不继承持久能力、不取得秘密解密能力；HTTP 的 control 锁与版本存储的事务边界保留在各自原位置。

## 执行与基础设施

| 责任 | 实现 |
| --- | --- |
| 固定快照、Job 构造与发布、supervisor 启停 | `execution/runs.py` |
| 包内容校验 | `execution/bundles.py` |
| 稳定进程入口、调度恢复与容量、单次 Harbor 执行 | `execution/worker.py`、`scheduler.py`、`runner.py` |
| 资源回收与进程组终止、证据审计与终态发布 | `execution/resources.py`、`audit.py` |
| 进程身份/安全环境、作者输入/来源/配置 | `execution/processes.py`、`author_inputs.py`、`sources.py`、`config.py` |
| Harbor 适配 | `execution/agents.py`、`environments.py`、`agent_tools.py` |
| 持久锁、SQLite、FIFO 唤醒、JSON、树与输入摘要 | `persistence/store.py`、`wakeup.py`、`files.py` |
| 私有文件、共享错误、脱敏与令牌 | `security/files.py`、`errors.py`、`credentials.py`、`access_tokens.py` |
| 评分、可比性与展示 | `results/reports.py`、`presentation.py` |
| CLI 参数、远程 HTTP/profile、服务启动 | `commands/main.py`、`remote.py`、`service.py` |

包校验供上传、附件与提交共用，不依赖提交组合。输入摘要在 `persistence/files.py`；安全投影在 `service/views.py`，机器展示不反向导入 Application。调度观察独立于接纳规则和机器 DTO；接纳规则与机器投影共同使用它。契约只依赖 DTO、低层错误和常量，不依赖综合数据对象。

执行到服务的必要组合点是：

- `runs.submit` 准备阶段通过 `TeamConfiguration(ServiceData(store))` 取得固定来源凭据和作者输入，调用隔离 `source_call`；发布阶段用 `ServiceData.submission/allow_publish` 固定原始摘要、检查取消与账户许可。这些步骤仍在原有 control 锁和发布顺序中。
- `scheduler` 取得执行凭据并调用 `lifecycle.prepare_one/maintenance`。持久准备只构造 ServiceData；保留维护额外构造 `Evidence(data)` 生成安全归档，不构造 Application、配置或附件。
- `runner` 在实际执行前核对固定输入和执行凭据；`audit` 用审计凭据清洗和检查终态证据。执行许可与审计许可保持分离。`scheduler.Controller` 先持久化 finish_status/finish_reason，再分别派发终止和资源清理；清理确认后提交终态释放容量，审计另用串行通道，完整 report 写成后才提交 CLEAN。

调度使用 SQLite 工作记录和 `state/scheduler.wake`（0600 owner-only FIFO），消息只提示重读持久事实。`Store.control()` 释放锁后通知，控制者用 `quiet_control()` 避免自唤醒；直接配置持久入口和 worker outcome 也通知。正常路径只查询待办/活动/待审计记录；定向存活检查每秒一次，心跳两秒、丢通知对账六十秒，维护三十秒。准备/审计/维护各一条通道，清理四条；终止每个活动 run 一条，降低容量不影响已运行任务终止。executor 没有无界待办队列。

`Store.evidence()` 以 `evidence-locks/<run>.lock` 串行审计、归档、删除及在线快照。持 run 锁不反取 control；持 control 的删除/快照仅非阻塞尝试证据锁，忙时返回可重试结果。停止在短 control 内检查空闲、发布带 PID/birth 的停止记录再发 SIGTERM，等待在途工作收束；新的受理在此期间拒绝。启动先持单实例锁并发布 FIFO/身份，再构造 Store；observed 由实际控制路径更新，不能把初始化写库等待报成 ready。

这些是固定输入、授权与持久发布的组合边界，不要求所有包严格单向。延迟导入的执行组合点不代替上述职责归属；文件 IO 和通用校验没有上层服务依赖。

## 前端维护入口

| 责任 | 实现（相对 `frontend/src/`） |
| --- | --- |
| 会话入口、会话状态、外壳与路由 | `App.tsx`、`app/useSession.ts`、`app/Shell.tsx`、`app/AppRoutes.tsx` |
| 登录、setup、改密、PAT | `features/account/` |
| 实验列表、新建、提交状态、详情、评分、比较 | `features/experiments/` |
| 详情快照、评分报告与产物部件 | `features/experiments/{Overview,Report,Artifacts}Panel.tsx`、`Rewards.tsx` |
| 共享附件版本、就绪与维护提示 | `features/attachments/`、`features/admission/` |
| 管理导航、共享刷新与全局编辑锁 | `features/admin/Admin.tsx`、`useAdminActions.ts` |
| 来源、Docker、数据集/作者参数、模型/key、账户、容量面板 | `features/admin/{Sources,Runtime,Datasets,Models,Users,Limits}Panel.tsx` |
| 管理表单、模型表单、作者参数、共享 Docker 观察 | `features/admin/{AdminForm,ModelForm,AuthorInputs}.tsx`、`useDockerDiagnostics.ts` |
| 公共 UI、加载、HTTP、展示 | `components/shared.tsx`、`components/ui/`、`hooks/useLoad.ts`、`api.ts`、`presentation.ts` |
| 生成类型及其导出来源 | `generated/contracts.ts`、仓库 `tools/browser_contract.py` |

管理面板自身位于 TabsContent 外，切换标签不丢失所选对象和筛选状态；内容由现有 Tabs 决定显示。共享保存包装在写入和目录刷新完成前锁定所有编辑器，表单自身继续清除秘密输入。前端调用者不能自行声明响应类型，方法、路径和 DTO 关系仍由生成契约约束。展示模块独立于 HTTP 传输。

## 进程与验证边界

console script 为 `harbor_helper.commands.main:main`。调度器与 worker 保持 `python -m harbor_helper.execution.worker supervise|run`；隔离 Hub 子进程保持 `python -m harbor_helper.service.sources`。Job 的 agent 类路径和 `execution.environments:NativeDockerEnvironment` 保持稳定。

进程 fixture 复制完整包后，必须在实际查找绑定的模块替换外部能力。例如调度回收 patch `execution.scheduler.cleanup/stop_group`，精确 Docker 命令 patch `execution.resources.run_command`，worker 启动 patch `execution.scheduler.subprocess.Popen`，单次执行 fixture 写入 `execution/runner.py`。不得在旧 worker 路径留别名使补丁虚假成立。Harbor Trial 构造中的内核能力探针也是外部 Docker 边界，代理参数测试应明确替换它。

回归使用独立 HOME/state/master 和白名单环境；完整 Python 回归需在不提供 docker 可执行文件的 PATH 下运行。真实 Docker/Hub/模型验证与 fixture 结果分开说明。运行与协作入口见[交接](../HANDOFF.md)与[开发规则](../guides/development-workflow.md)。
