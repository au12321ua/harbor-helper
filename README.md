# harbor-helper

包版本：`0.2.0`。部署须固定到经审查验收的提交/tag；源码版本号不代表候选已经发布或部署。

受邀团队共享的 Harbor 实验工作台。成员通过浏览器提交、观察、取消自己的实验、比较、重跑和下载；管理员在网页邀请成员、配置数据集、团队模型/key及容量。所有人共享结果，提交身份保留。CLI与Web共用持久队列。

## 成员使用

打开部署负责人提供的网址，用受邀账户登录。选择管理员已验证的数据集、任务和模型方案，填写实验名称后提交；尝试次数、并发和等待倍率等在高级参数中。结果页区分有效零分、缺评分与执行失败。重跑创建归当前提交者的新实验，可能再次产生模型费用。

成员无需SSH、服务器state路径、个人模型key或安装CLI。管理员日常业务配置也在网页完成。

## Linux 服务安装与管理

需要 Linux、Python 3.12–3.13、uv 和可用的用户级 systemd。使用专用服务账号；由部署管理员配置该账号的开机 user manager（例如 `loginctl enable-linger`），HTTPS/代理/证书由部署环境处理。首次网页设置不需要 Docker、Hub 或模型请求；实际实验需要 Docker/Compose 和授权的数据集。

从已验收的固定提交安装，选择全新私有目录和唯一实例名：

```bash
python3 scripts/service.py install --directory /absolute/private/hh-team --instance team --port 8000
python3 /absolute/private/hh-team/manager/service.py start --directory /absolute/private/hh-team
python3 /absolute/private/hh-team/manager/service.py status --directory /absolute/private/hh-team
```

安装导出固定提交到 `releases/<SHA>` 并锁定安装依赖，运行时不依赖工程 worktree；`state/`、`private/`（主密钥及引导文件）、`home/` 和 `logs/` 分开。输出只给引导凭证文件位置，部署负责人在受保护终端读取并私下交给首管理员。管理员在网页首次设置，然后在“团队管理”邀请成员、配置数据集、模型/key与容量。不要把引导凭证贴入群聊、命令参数或 Git。

HTTP 与 scheduler 为独立 unit；`--part http` 或 `--part scheduler` 可单独启停。HTTP 启动及首次设置不会派生 scheduler；未初始化的 scheduler 等待网页设置完成。`start` 始终使用已安装 release，不会因 Git HEAD 改变而升级。

正常维护请在管理员网页“团队管理 → 容量与保留”走两阶段停止：先明确关闭新受理，再等待全部已受理任务结束，或明确取消全部未完成任务并清理资源。可退出等待，入口仍关闭。主机脚本入口：

```bash
python3 /absolute/private/hh-team/manager/service.py maintain --directory /absolute/private/hh-team --close-admissions --mode wait --wait-seconds 3600
# 明确取消全部（准备、排队、执行），保留历史，可重跑
python3 /absolute/private/hh-team/manager/service.py maintain --directory /absolute/private/hh-team --close-admissions --mode cancel
python3 /absolute/private/hh-team/manager/service.py stop --directory /absolute/private/hh-team
```

不带 `--close-admissions` 时，开放的入口需要交互输入 `yes`；非交互调用拒绝并保持原开关。已关闭则跳过确认。等待超时只退出客户端等待，持久停止意图继续生效。直接 `stop`/SIGTERM 则中断执行并尝试清理，保留 queued 和未发布 preparing，维护开关保持原值；这不是断点续跑。

升级、备份恢复、卸载及 systemd 限制见[Web 服务指南](docs/guides/web-service.md#linux-生命周期与维护)。旧 `start-local.sh` 现在转发同一生命周期管理器，使用相同参数；不会隐式选择新发布。

## 从干净环境启动 Web

以下由部署负责人一次完成，在已取得源码的项目根目录执行。需要：

- Linux、Python **3.12–3.13**、[uv](https://docs.astral.sh/uv/getting-started/installation/)。Harbor由锁文件安装为0.23.0。
- Node.js **20.19及以上的20.x，或22.12及以上**、npm，用于构建网页。
- 真正执行实验时，服务账户须能访问Docker daemon与Compose插件；作者任务所需镜像、依赖和网络须可用。私有Hub数据集需要权限。首次网页设置不需要先发模型请求。

```bash
uv sync --locked
cd frontend
npm ci
npm run build
cd ..
```

构建写入`src/harbor_helper/static/`。HTTP 进程提供网页与 API；另一个终端独立运行 scheduler。生产推荐上面的 systemd 安装入口。下面的手动HTTP服务，它同时提供网页和相对`/api/v1`接口；不需要启动Vite或单独部署前端。

选择全新服务目录和**state之外**的私有部署目录。下面是当前账号可写的示例；不要用已有服务目录重新初始化：

```bash
mkdir -p "$HOME/harbor-helper/service" "$HOME/harbor-helper-private"
chmod 700 "$HOME/harbor-helper" "$HOME/harbor-helper/service" "$HOME/harbor-helper-private"

uv run harbor-helper service serve \
  --root "$HOME/harbor-helper/service" \
  --setup-token-file "$HOME/harbor-helper-private/setup-token" \
  --master-key-file "$HOME/harbor-helper-private/master.key" \
  --host 127.0.0.1 --port 8000
```

另一个终端独立启动调度器（同一 state，不继承个人模型或 Hub 凭据）：

```bash
uv run harbor-helper service scheduler --root "$HOME/harbor-helper/service"
```

保持此终端运行，在**部署机浏览器**打开 <http://127.0.0.1:8000/>。若8000被占用，换一个空闲端口并同步网址。供其他机器访问时，部署者须选择可达的`--host`和网址；`0.0.0.0`是监听地址，不是浏览器网址。HTTPS、代理、证书及域名由部署环境配置。

### 首次管理员设置

上面的手动 `service serve` 会自动生成权限0600的引导凭证文件，只提示文件位置；一条命令入口在交互终端直接显示，重定向时只给路径。部署负责人在自己的受保护终端读取它，通过私下渠道交付管理员，勿贴到群聊、命令参数或Git：

```bash
cat "$HOME/harbor-helper-private/setup-token"
```

管理员在首次网页填写引导凭证、团队名称、账户和密码（至少12位），完成后用新账户登录。首次设置只允许成功一次，随后关闭设置接口，不开放注册。首次设置完全在网页完成；没有 `service init` 命令。

主密钥在首次初始化时自动创建为32随机bytes，权限0600，存于上面的外置`master.key`；不要自己写一个短字符串代替。模型key和Hub PAT在服务端加密保存，原值不回传网页。备份和恢复必须保全**完整state及原外置主密钥**，不能换一个新master恢复旧密文。

管理员随后在管理页：

1. 配置团队Hub来源；保存数据集的`owner/name@版本`，验证任务清单并选择默认。
2. 创建提供商、团队key和模型方案，明确选择绑定。列表筛选只改变查看范围，不修改绑定。
3. 邀请成员账户，按需要设定容量与保留参数；将网址和初始账户通过受保护渠道交付成员。

保存key不等于真实provider认证或推理成功，来源验证也不保证作者环境能执行。Harbor按作者Dockerfile/Compose构建运行；helper不替换作者镜像或网络。新模型实验可准备固定公共工具并在作者环境离线使用，旧已受理契约保留；细节见[服务指南](docs/guides/web-service.md)。

### 关闭与维护

关闭浏览器不停止实验。上述前台终端`Ctrl-C`只停止HTTP，独立调度器及已受理任务继续；用同样的state和原主密钥重启`serve`可继续观察，**不要重新初始化**。

完整停机由部署负责人停止接收新提交、等待或取消全部未终态任务并确认资源释放，停止HTTP后再停止该服务调度器；没有`service stop`命令。准确停机与备份步骤见[维护说明](docs/guides/web-service.md#完整停机)。这不是成员每天必做操作。

## 其他入口

- [远程CLI](docs/guides/web-service.md#成员远程-cli)：可选的自动化入口，使用成员账户而非个人模型key。
- [文档导航](docs/README.md)：安装、运行、架构、验收标准及历史设计。
- [开发交接](docs/HANDOFF.md)：维护入口、兼容策略与验证边界。

Python 与自动化 Agent 接入见 [SDK 与 MCP](docs/guides/sdk-mcp.md)。
