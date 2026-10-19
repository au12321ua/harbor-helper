# harbor-helper

受邀团队共享的 [Harbor](https://github.com/laude-institute/harbor) 实验工作台。成员通过浏览器提交、观察、取消自己的实验、比较、重跑和下载；管理员在网页邀请成员，配置数据集、团队模型/key及容量。所有人共享结果，保留提交身份；CLI、SDK 与 MCP 共用服务端队列。

包版本为 `0.2.0`，部署应固定到经审查验收的提交/tag；包版本号不代表该提交已经发布或部署。

## 成员使用

打开部署负责人提供的网址，用受邀账户登录：

1. 在“新建实验”选择已验证的数据集、任务和模型方案，填写名称后提交；尝试次数、并发与时长在高级参数中。附件可选明确版本，默认无附件。
2. 在共享实验中查看准备进度、日志、评分报告和产物。有效零分、缺评分与执行失败分别展示；审计受限的证据不可下载。
3. 比较实验时先核对可比性；可下载 JSON/CSV。重跑保留原冻结条件，“复制配置新建”允许修改后提交，两者都创建归当前提交者的新实验。

成员无需 SSH、服务器路径、个人模型 key 或安装 CLI。关闭浏览器不停止实验；重跑和新提交可能产生模型费用，时长/并发限制不是金额预算。

## 安装团队服务

需要 Linux、Python **3.12–3.13**、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和用户级 systemd。使用专用服务账号；部署管理员负责 user manager 自启（如 `loginctl enable-linger`）以及网络入口、HTTPS/代理/证书。实际实验另需 Docker/Compose、作者依赖和数据集访问权限。

从已验收的固定提交安装，选择全新私有目录和唯一实例名：

```bash
python3 scripts/service.py install --directory /absolute/private/hh-team --instance team --port 8000
python3 /absolute/private/hh-team/manager/service.py start --directory /absolute/private/hh-team
python3 /absolute/private/hh-team/manager/service.py status --directory /absolute/private/hh-team
```

安装导出固定提交并锁定依赖，运行不依赖开发 worktree。默认监听 `127.0.0.1:8000`；供其他机器访问时配置可达的 `--host` 和网址。部署负责人按输出的文件位置私下交付引导凭证，首管理员在网页完成团队设置，再配置数据集、模型/key和受邀账户。

state 与主密钥分开保存，秘密不回传网页或提交 Git。备份和恢复必须保全完整 state 与配对的主密钥。正常维护先在网页关闭新受理，明确等待全部任务结束或取消全部，确认资源释放后再停服务。

安装参数、手动启动、维护、升级、回退及卸载见 [Web 服务指南](docs/guides/web-service.md)；网页版本检查与更新接入见 [网页版本与更新](docs/guides/web-updates.md)。

## 开发与验证

从 `dev` 建独立分支和 worktree，见 [开发规则](docs/guides/development-workflow.md)。构建前端需要 Node.js **20.19+ 的 20.x，或 22.12+**；CI 使用 Node 22。开发模式的 HTTP 与 scheduler 启动见 [手动启动](docs/guides/web-service.md#开发与手动启动非-systemd-安装)。

GitHub Actions 与 Gitea Actions 共用隔离验证入口：

```bash
python3 scripts/verify.py --prepare \
  --browsers /absolute/private/playwright-cache \
  --output /absolute/private/verification-new-directory
```

它安装锁定依赖，检查 Python、类型契约、前端构建产物，运行 pytest 和浏览器 fixture；不使用团队 state 或真实模型凭据。运行前提、Python 3.13 检查与远端 CI 说明见 [自动化验证](docs/guides/automation-ops-ci.md)。

## 其他入口

- [文档导航](docs/README.md)：按使用、集成与维护查阅。
- [远程 CLI](docs/guides/web-service.md#成员远程-cli)、[SDK 与 MCP](docs/guides/sdk-mcp.md)、[研究客户端 skill](docs/guides/research-skill.md)。
- [开发交接](docs/HANDOFF.md)、[源码职责](docs/architecture/source-layout.md)、[验收标准](docs/reference/service-acceptance.md)。
