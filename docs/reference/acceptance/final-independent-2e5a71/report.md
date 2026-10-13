# 0.2.0 最终独立验收报告

**限定结论：通过本报告列出的最终整合行为和 0.2.0 包交付检查；未验证生产升级，不构成发布或部署批准。** 固定受测候选 `2e5a71f2e7e47c6b19cca2d2219ae62384502097`，分支引用 `origin/feature/final-integration-candidate`。

## 边界与现场

先读项目 `AGENTS.md`、`docs/HANDOFF.md` 与本机 `.local/LOCAL_ENVIRONMENT.md`。主树当时为 `master 9451363155674f138123c94c5e1ba51687139b36`，`origin/dev` 为 `6db930d37b7e0f78e20fe3ec8221357b286b6352`；本次结束时两引用仍是这两个 SHA，主树 clean。候选在新的 detached snapshot `/tmp/hh-checker-wt-2e5a71-20261012` 执行。候选 tracked 产品/测试/skill/锁文件与 `2c104ac1bf5d3b565fef8264c44b7c74922b9752` 无差分，build 生成的 static 与候选逐字一致。

启动前实时观察 `127.0.0.1:8768` 无 listener；正式 state、外置 master 与 setup token 只读 stat/权限/大小，未读内容、复制、写入或启动。测试使用独立 HOME、XDG、Harbor/HF/Docker profile、缓存、state 和 state 外的 fake master/PAT。清除继承环境，未用真实 Hub、Docker/Harbor、Oracle 容器、模型 key 或付费模型请求。浏览器请求没有被拦截；只在独立复制包中替换 dataset source/image identity/worker execution adapter，并使用确定性 `checker-verifier-v1` 评分。

## 实际整合检查

本轮自选 `fixture/checker-cedar@1` / `fixture/checker-task` 输入，同组固定 agent=Oracle、attempts=1、concurrency=1、wall_seconds=120、同一 verifier。CLI 与浏览器分别完成无附件、v1、v2 三项；不做 CLI 组与浏览器组的跨组效果比较。

- 真实本机 HTTP 提供候选静态页面和相对 API。成员浏览器登录后选择已验证 fixture dataset，提交无附件/v1/v2，查看共享记录；每个安全评分报告均由下载按钮实际下载。浏览器比较无附件与 v1 可比，fixture delta 为 +1；v1 与 v2 显示版本变化。桌面比较、窄屏共享列表、身份、交互、overlay、pageerror 与 console 检查通过；浏览器唯一 401 是登录前匿名 `/me`。
- 页面完成一次本人待处理取消：取消前状态 `preparing`，取消后 `cancelled`。从页面对本人成功实验重跑，受理归 `fixture-member`，重跑报告随后可用。
- 一次性代理先观察到上游真实 `202`，再向 CLI 合成返回 `504`。CLI用原键和同成员替换凭证找回原 submission；未创建补偿键。撤销旧 PAT 后旧凭证返回 `401`；只读凭证实际 submit 返回 `403`。
- 管理员在网页暂停新受理；成员通过真实 HTTP 请求收到 `503 maintenance_paused`。同一暂停窗口，成员用旧幂等键仍找回原受理。管理员网页恢复后 readiness 重新允许受理。
- 另用独立浏览器整合专项观察维护期间的排空：管理员网页暂停后，已受理的第一项继续执行并在暂停仍生效时产出可下载报告；第二项由提交者本人取消，最终 run=`cancelled`、resource=`released`，fixture 返回的安全报告仍为 `available`；新提交被拒绝为 `503 maintenance_paused`，网页恢复后 readiness 显示未暂停。固定单 worker，执行 fixture 对第一项注入 20 秒有界工作，浏览器总等待分别限制在 60 秒；本专项不依赖真实容器。结果见 `live-maintenance-drain-final3/capture/maintenance-drain-result.json`。
- 新发布 v3 后，历史 v1 run 的 manifest 字节 SHA 仍为 `93638bd150af3e7186e7bc00cb22441de0fdb5eb651da093668fe93cd4785bd4`。
- 安全/资源轴采用明确标注的合成 fixture：audit=incomplete 时 resource=released、report=blocked 且远程 report 被拒绝；另一个 audit=clean、状态合成 `cleanup_blocked` 的 run 显示 report=blocked 且 active_jobs/active_trials 各增加 1。没有容器故障或真实清理失败。
- 评分边界通过候选报告函数与 native-shaped fixture 检查：有效 `reward=0` 保持有效；空 rewards 映射为 `missing_score`；带合成异常映射为 `execution_failure`。后两项是合成输入，不代表真实 worker/模型失败。

## 0.2.0 包与交付

`uv sync --locked --group dev`、`npm ci`、`npm run build` 与从项目根目录运行 `uv build` 均退出 0。独立 wheel 实际标识 `0.2.0`，console entry `harbor_helper.cli:main` 从解包 wheel 导入并执行 `--help` 成功。wheel 的所有 tracked Python/static 字节匹配候选；sdist 的 568/568 tracked 文件均存在并匹配，研究 skill 2 个文件字节一致。相对 `8519109ee3c7d012d826fdfa5df7ec894b783c71` 比较，uv 解析依赖、hash 与 integrity 未变（仅 helper 自身版本字段变更）；相对版本修正提交 `2c104ac`，后续差分只在报告/证据文档。

- wheel SHA256：`69cecd3cbf91b14ed4490cfd1406451ec6e36505453055ee36fb17810b5bda1a`
- 本轮 sdist SHA256：`75d454f1a0b2a2e90ad825fd871f4a8de78e36bfea497bd346e666c157a44283`

构建产物仅留在独立 `/tmp` 目录，未发布。先前工程报告列出的 sdist SHA 属于其固定构建；本轮重新构建的 tarball SHA 不同，但内部全部 tracked 文件均逐字相同。

## 失败保留、收尾与限制

早期浏览器脚本路径解析、隔离 Chromium 路径、fixture 登录口令、取消请求字段、审计夹具，以及本轮维护排空 harness 对 `run_id`/状态轮询时序和报告状态的假设错误，均保留原 stdout/stderr/退出码。按根因修正 harness，最终维护排空场景退出 0；失败过程中发现的 worker PID/birth 在复核时均已退出。最终完整集成命令、浏览器、合成安全门、报告轴、wheel CLI、源码分发完整性及最终全 state 的 PID/birth 和隔离端口审计均退出 0。失败原件在各 `live*/capture/` 与顶层 `capture/`，索引见 `SHA256SUMS`。

收尾时对所有本轮隔离 run 的 PID/birth 做复核，无匹配存活 worker；每个记录的 HTTP/代理端口均关闭。测试 state、fixture 私有目录及缓存保留本地供 Root 复核，不在 Git 或证据索引中；不包含凭据值或整包 state。主工作区、正式服务/state、dev/master/tag 均未改动。

未覆盖真实 Harbor/Docker/Hub/Oracle/模型运行、独立 scheduler 重启恢复、web 容量额度修改与跨入口额度拒绝、并发压力、迁移/一致备份/恢复、代理 HTTPS、多机与断电边界；本轮不重复 352 Python / 29 UI 全量、API 全矩阵或历史所有专项。部署前停写、全写者确认、同一时点 state 备份与原 master 保全、兼容迁移和回退仅为交接检查点，未演练。历史工程证据保持原版本含义。
