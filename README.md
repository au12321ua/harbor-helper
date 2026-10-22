# harbor-helper

> 本分支 `feature/rewrite` 正在按[重写目标设计](docs/design/README.md)整体重写，可能无法运行。下文描述 `9ff43b5` 基线代码；正式使用请以 `dev` / 发布版本为准。

包版本：`0.2.0`。部署须固定到经审查验收的提交/tag；源码版本号不代表候选已经发布或部署。

受邀团队共享的 Harbor 实验工作台。成员通过浏览器提交、观察、取消自己的实验、比较、重跑和下载；管理员在网页邀请成员、配置数据集、团队模型/key及容量。所有人共享结果，提交身份保留。CLI与Web共用持久队列。

## 成员使用

打开部署负责人提供的网址，用受邀账户登录。选择管理员已验证的数据集、任务和模型方案，填写实验名称后提交；尝试次数、并发和等待倍率等在高级参数中。结果页区分有效零分、缺评分与执行失败。重跑创建归当前提交者的新实验，可能再次产生模型费用。

成员无需SSH、服务器state路径、个人模型key或安装CLI。管理员日常业务配置也在网页完成。

## 一条命令启动本机空实例

在干净的 Git checkout 中运行（Linux、Python 3.12–3.13、uv）：

```bash
./scripts/start-local.sh
```

入口复用已提交的生产 static，不需要 Node 或前端构建。它从当前固定提交导出独立发布目录并锁定安装依赖；默认仅监听 `127.0.0.1` 的空闲端口。代码、独立 HOME、持久 state、外置 master/setup 和日志位于 `~/.local/share/harbor-helper-local/`，不使用仓库旧 state 或个人模型/Hub 登录。

1. 打开输出的 URL，直接使用交互终端显示的引导凭证；输出被重定向时只显示本机凭证文件路径，不显示值。
2. 网页首次设置创建管理员，然后登录，在“团队管理”配置业务。新空实例不迁入旧账户或实验；首次设置无需 Docker/Hub/key，真实实验仍需这些依赖和授权。
3. 再运行显示已有实例；`./scripts/start-local.sh stop` 停止自己的 HTTP 和空闲调度器，重新运行后原账户与主密钥保留。

```bash
./scripts/start-local.sh status
./scripts/start-local.sh restart
./scripts/start-local.sh --port 8780
./scripts/start-local.sh --directory /absolute/private/local-instance
```

`--port` 用于停止状态下选端口；多实例用不同 `--directory`，后续 status/stop 使用同一路径。日志路径随状态输出。stop 遇未终态任务会拒绝停止调度器，需重新启动网页取消/等待；它不会强杀执行任务。坏记录或主密钥缺失时按诊断检查原文件，不重新初始化。更换代码版本前先确认 stop 成功；旧发布目录不会自动删除。此入口用于同机本地使用，远程访问、HTTPS和生产迁移见下文。

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

构建写入`src/harbor_helper/static/`。生产只运行下面一个HTTP服务，它同时提供网页和相对`/api/v1`接口；不需要启动Vite或单独部署前端。

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

保持此终端运行，在**部署机浏览器**打开 <http://127.0.0.1:8000/>。若8000被占用，换一个空闲端口并同步网址。供其他机器访问时，部署者须选择可达的`--host`和网址；`0.0.0.0`是监听地址，不是浏览器网址。HTTPS、代理、证书及域名由部署环境配置。

### 首次管理员设置

上面的手动 `service serve` 会自动生成权限0600的引导凭证文件，只提示文件位置；一条命令入口在交互终端直接显示，重定向时只给路径。部署负责人在自己的受保护终端读取它，通过私下渠道交付管理员，勿贴到群聊、命令参数或Git：

```bash
cat "$HOME/harbor-helper-private/setup-token"
```

管理员在首次网页填写引导凭证、团队名称、账户和密码（至少12位），完成后用新账户登录。首次设置只允许成功一次，随后关闭设置接口，不开放注册。无需先执行`service init`；该命令仅保留给兼容的终端初装方式。

主密钥在首次初始化时自动创建为32随机bytes，权限0600，存于上面的外置`master.key`；不要自己写一个短字符串代替。模型key和Hub PAT在服务端加密保存，原值不回传网页。备份和恢复必须保全**完整state及原外置主密钥**，不能换一个新master恢复旧密文。

管理员随后在管理页：

1. 配置团队Hub来源；保存数据集的`owner/name@版本`，验证任务清单并选择默认。
2. 创建提供商、团队key和模型方案，明确选择绑定。列表筛选只改变查看范围，不修改绑定。
3. 邀请成员账户，按需要设定容量与保留参数；将网址和初始账户通过受保护渠道交付成员。

保存key不等于真实provider认证或推理成功，来源验证也不保证作者环境能执行。Harbor按作者Dockerfile/Compose构建运行；helper不替换作者镜像或网络。新模型实验可准备固定公共工具并在作者环境离线使用，旧已受理契约保留；细节见[服务指南](docs/guides/web-service.md)。

### 关闭与维护

关闭浏览器不停止实验。上述前台终端`Ctrl-C`只停止HTTP，后台调度器及已受理任务继续；用同样的state和原主密钥重启`serve`可继续观察，**不要重新init**。

完整停机由部署负责人停止接收新提交、等待或取消全部未终态任务并确认资源释放，停止HTTP后再停止该服务调度器；没有`service stop`命令。准确停机与备份步骤见[维护说明](docs/guides/web-service.md#完整停机)。这不是成员每天必做操作。

## 其他入口

- [远程CLI](docs/guides/web-service.md#成员远程-cli)：可选的自动化入口，使用成员账户而非个人模型key。
- [文档导航](docs/README.md)：安装、运行、架构、验收标准及历史设计。
- [开发交接](docs/HANDOFF.md)：维护入口、兼容策略与验证边界。
