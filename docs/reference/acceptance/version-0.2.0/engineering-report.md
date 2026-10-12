# 0.2.0 版本标识补验

Root已确定本轮下一版本为 **0.2.0**。版本实现固定 `2c104ac1bf5d3b565fef8264c44b7c74922b9752`，来自候选 `8519109ee3c7d012d826fdfa5df7ec894b783c71`；只同步包标识，没有产品行为变化。本次工程完成待Root固定复核和一次最终Checker，没有发布、创建tag或部署。

## 变更和旧证据

改动仅五个文件：pyproject project.version、uv.lock的本地harbor-helper版本、frontend/package.json版本、frontend/package-lock.json顶层与root package版本、README候选包标识。Python/前端依赖规格、全部解析版本/下载hash/integrity和其他锁元数据结构与8519109完全相同。

生产Python、frontend/src与原QA、tests、skills均未变化。生产build重新执行，输出同名JS/CSS，`src/harbor_helper/static/`字节和Git树均未变化。没有新增版本API、CLI --version或界面元素。

[8519109原工程报告](../final-integration/engineering-report.md)SHA256仍为 `81934e3bcb35584406659d8f9ebf112329e56a271f3056c09995ec39c6a11133`；原154项索引、26份独立归档与全部历史原输出/失败逐对象不变。旧报告中的0.1.0属于其固定版本观察，不回写成0.2.0。原全量352 Python/29 UI实际受测产品为6db930，完整串联固定efbc359；本轮不重跑它们，也不将新报告提交称为这些检查实际受测SHA。

## 本轮实际检查

在原独立feature/worktree内操作；全新 `/tmp/hh-version-020-evidence` HOME/XDG/Harbor/HF/Docker profile和uv/npm cache，子进程只使用记录的白名单环境（等价env-i），未继承真实凭据或代理。没有启动HTTP/scheduler/state或调用Hub/Docker/模型。构建依赖公开下载的可能性与锁定安装分开于真实实验执行。

| 检查 | 结果/前置 | 原输出 |
| --- | --- | --- |
| uv sync --locked --group dev | 退出0，安装editable元数据0.2.0；依赖不变 | capture/uv-version-sync.* |
| npm ci | 退出0，依package-lock安装，0 vulnerabilities | capture/npm-version-ci.* |
| npm run build | 固定2c104ac，退出0；static逐字不变 | capture/build-version.* |
| uv build | 固定2c104ac，0.2.0 sdist/wheel生成，退出0 | capture/package-version.* |
| 版本/锁差分、安装元数据、源包/wheel逐字检查 | 固定2c104ac；最终退出0 | capture/version-check-final.* |
| wheel CLI console入口执行 --help | 新包解包目录优先导入，断言导入路径位于该目录，console入口名称/帮助及退出0 | capture/wheel-cli-final.* |

uv/npm安装时HEAD仍8519109且五个已批准标识改动尚未提交；command.json如实记录该HEAD，不伪造为干净固定提交。build/打包和最终验证在已提交且clean的2c104ac运行。

最终检查读取0.2.0 wheel的METADATA、entry_points；所有tracked Python/static字节匹配。sdist在2c104ac的**全部tracked文件**逐字匹配，包括README/文档、frontend源码/QA、锁、完整可复制研究skill及原历史证据。wheel包含Python/static，skill完整目录通过sdist/仓库交付，不冒称wheel中有独立skill。CLI没有访问服务/准备任务或执行实验。

## 检查脚本失败与修正

第一次version-check退出1：wheel/源包/元数据全部检查通过，但 `python -m harbor_helper.cli --help` 默认usage程序名是cli.py，检查脚本误断言stdout应含harbor-helper。该CLI本身退出0；失败的检查stdout/stderr/exit、wheel-cli原输出和check-version-first.py保留。

随后使用wheel声明的console入口 `harbor_helper.cli:main`，按安装console脚本方式设argv为harbor-helper/--help，并断言导入来自解包wheel；原名称断言保持，最终CLI及总检查退出0。只修本轮检查调用方式，未改生产代码、旧测试或旧断言。

## 产物与交接

0.2.0 wheel SHA256：`69cecd3cbf91b14ed4490cfd1406451ec6e36505453055ee36fb17810b5bda1a`。

0.2.0 sdist SHA256：`7debaf1dc3105c9a7e53b89828542227841265cc0cf908338d10467b3e9f86df`。

二进制包仅本地 `/tmp/hh-version-020-evidence/dist/` 留供复核，未上传/发布；该包对应2c104ac，后续仅报告/归档/导航的提交不倒称打包实际受测版本。所有新capture、检查脚本、补报告索引为本目录 `SHA256SUMS`，旧索引未改。元数据提供补验基点/数量和包摘要；没有截图/state/home/profile/cache/private或秘密原值入库。

主树/master、dev、全部tag、正式服务/state/外master未操作；仅正常push本feature。末提交仅补报告/安全原始证据与导航，`src/frontend/tests/skills/pyproject.toml/uv.lock/README.md`须与2c104ac对象相同；交付SHA从Git引用取得。正式发布、迁移/停写与一致state+原master保全、回退沿原交接检查点，必须由Root固定复核和最终Checker后另依授权操作，不删维护/幂等数据或用过时state回退。
