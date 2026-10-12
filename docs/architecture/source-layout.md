# 源码职责与兼容

Python实现位于`src/harbor_helper/`的职责包。CLI参数、HTTP路径、持久state/schema、Job/manifest字段和运行权限维持原契约。前端仍构建到包根`static/`；目录迁移不要求用户重新初始化、换主密钥或改变作者镜像/网络。

## 维护入口

| 板块 | 实现 | 责任 |
| --- | --- | --- |
| CLI | `commands/main.py`、`local.py`、`remote.py`、`service.py` | 参数/模式分流、旧本地操作、远程HTTP与profile、服务启动与成员登录 |
| 团队服务 | `service/api.py`、`application.py`、`attachments.py`、`attachment_contracts.py`、`lifecycle.py` | HTTP/SPA、受理/权限/安全结果、持久输入准备与保留维护 |
| 团队数据与配置 | `service/data.py`、`configuration.py`、`setup.py` | 受邀账户、会话、凭据版本/加密/容量、来源/default、外置引导 |
| 外部客户端 | `service/sources.py`、`docker.py` | 隔离Hub子进程、只读Docker诊断 |
| 执行调度 | `execution/runs.py`、`worker.py`、`processes.py` | 固定快照/Job/发布、调度/恢复/取消/审计、PID出生身份与安全进程环境 |
| Harbor适配 | `execution/agents.py`、`environments.py`、`agent_tools.py` | 严格原生Options/实验包、作者环境窄stop/阶段证据、公共固定工具准备与暂存清理 |
| 实验输入 | `execution/config.py`、`sources.py` | 非秘密配置/校验、作者任务下载与快照摘要 |
| 持久基础 | `persistence/store.py`、`files.py` | SQLite队列/control锁、JSON与输入digest |
| 安全 | `security/local_auth.py`、`files.py`、`errors.py`、`credentials.py`、`access_tokens.py` | 本地身份授权、私有客户端文件、共享异常、脱敏/审计/秘密上下文 |
| 结果 | `results/reports.py`、`presentation.py` | 评分与可比性、安全诊断、human/JSON展示 |

包`__init__.py`仅说明职责，不汇聚业务或启动资源。内部调用、脚本和测试使用canonical路径，根部保留的文件只有必要兼容入口，业务实现不复制。

## 依赖与组合边界

CLI调用服务或执行，再使用持久、安全与结果基础。HTTP调用团队应用/数据；结果展示不调用CLI。文件IO没有服务/执行依赖，Store仅在更新错误字段时使用脱敏工具；remote使用安全文件IO，不依赖本地Auth生命周期。进程身份与运行环境清洗独立于worker，环境观察和工具下载不再为PID/命令工具反向加载整个调度器。

`runs.submit`和`worker`仍是本地/团队两种既有模式的组合边界：运行时显式选择Auth或ServiceData；团队准备调用隔离Hub来源和发布取消检查，调度器按service模式调用`service/lifecycle.py`。这些跨板块依赖保留原顺序、锁与异常，通过延迟import避免顶层循环，不引入注册器/插件框架或改写业务。`service/application.py`的受理可调用执行，`service/lifecycle.py`依赖应用与执行；应用不会在导入时反向加载生命周期。剩余组合依赖有明确位置，不能把“所有板块严格单向”当作已经实现。

## 公开与持久兼容入口

- `harbor-helper` console script仍为`harbor_helper.cli:main`；`python -m harbor_helper.cli`转发`commands/main.py`。
- 旧`python -m harbor_helper.worker`和`harbor_helper.service_sources`分别转发`execution/worker.py`与`service/sources.py`。canonical命令也可执行；普通import兼容入口别名指向同一实际模块对象，不复制其global状态。
- 历史Job的`harbor_helper.agents:HelperOpenCode`、`BundledOpenCode`、`BundledOracle`及`harbor_helper.environments:NativeDockerEnvironment`保留。新Job继续写这些持久兼容类路径；旧Job文件不改写。
- 公共工具下载子进程使用`python -m harbor_helper.execution.agent_tools`；无持久Job依赖旧agent_tools模块名。childPID/birth与暂存证据仍原契约。
- 其他旧根模块是内部实现，维护脚本、测试及当前说明已迁到canonical路径，不创建逐模块wrapper。credentials只有`security/credentials.py`一份状态，ContextVar与秘密列表没有旧路径副本。

## 文件、进程与历史边界

API从稳定包根定位static，Hub子进程从包根的父目录设置PYTHONPATH，源码树和安装wheel各自检查。进程fixture递归复制完整Python包，并在canonical文件注入明确外部边界fixture，不能把替换代码附到shim上。

服务启动不加载旧个人模型key；Hub仍临时HOME和白名单环境隔离；公共工具子进程无provider/Hub凭据。P2不改变运行、缓存或权限语义。旧无策略/缺倍率受理、C2严格类型校验、有效0/缺评分/失败、资源释放与审计容量规则由原回归及必要进程验证覆盖。

使用与设计入口见[文档导航](../README.md)。历史源码路径按其版本解释，当前维护使用本页路径。
