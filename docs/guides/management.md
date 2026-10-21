# 请求、版本与回收管理

网页“请求与目录管理”提供请求组、团队附件、数据集版本和回收站。准备失败、尚未生成实验、未受理的实验操作也能管理。成员管理自己的请求与附件，管理员可管理团队对象。回收不自动清空；永久删除是管理员在回收站执行的第二个动作。

## 来源与版本

管理员先登记作者/包名，再查询远端版本、手选并预览、确认不可变摘要。最近版本最多显示 200 个未撤回的数据集版本；201 项探测截断，无法判定完整性时明确提示。任务包和新导入的撤回版本拒绝。补充摘要可以预览，但不能用手填引用代替选版流程。版本枚举及抓取运行在隔离子进程，使用团队显式 Hub 凭据或隔离匿名身份，不读取服务账户的个人登录。

确认固定 `author/package@sha256:…`，不再次解析 latest。首次确认建立默认版本；后续导入不改原默认或历史请求。每个摘要分别检查和保存作者参数，空参数必须有明确检查记录。修复重试、失败恢复只读原摘要对应的参数，缺失、回收或已删除明确拒绝。普通按原条件重跑使用请求自己的已验证输入副本，附件目录停用、回收或删除不阻止它；原请求回收、输入损坏、凭据及执行条件限制仍生效。

团队默认数据集或默认版本不可用时，目录保持可读并显示未设置；提交必须明确选择可用来源，不回退另一数据集或旧 team.json。恢复不会自动恢复默认选择。

启动转换自动保留旧配置修订、提交、实验、父链、冻结信息、参数与附件版本。重名用可读的“升级前”标记区分。旧同源项标记待整理；管理员预览并合并，参数冲突须明确选择将来使用的原修订，所有原修订及归属保留。未验证草稿保留为资料，不伪造来源版本。旧 ID 成为解析别名，不能绕过目标回收或删除状态。原 `dataset_version` 仍是配置修订，`source_version` 仍是 Hub 凭据版本。

## 请求组与编号

重跑、修复、恢复和延伸持久记录直接来源与关联类型，属于同一请求组，名称不追加后缀。修改配置后新建可明确选择延伸原组或另建独立组。组创建者及管理员可改名，其他成员不能改名；改名不改冻结配置，详情保留提交时名称。空名可用，显示“未命名 · 短ID”。非空名称按 NFKC 和 casefold 检查团队唯一，回收期间占名。附件、数据集本地版本号和组内请求号永久删除后不复用。

## 两阶段回收

选择请求、数据集、附件、单版本或终态产物，先预览范围再移入回收站。整对象包括当前全部版本，范围改变要求刷新；批量操作逐项返回结果，不级联删除其他请求。活动请求必须先取消并等待资源释放，审计异常本身不永久阻止清理。

| 回收对象 | 正常读取及使用 | 恢复/清理 |
| --- | --- | --- |
| 请求 | 列表隐藏；直接详情、日志、报告、比较、证据、下载与派生拒绝；操作历史仅最小状态 | 本人或管理员恢复；管理员永久删除 |
| 数据集/版本 | 目录隐藏；选用、参数修改、版本抓取发布拒绝；别名同样受限 | 管理员恢复或永久删除，专属参数与缓存清理 |
| 附件/版本 | 目录隐藏；下载、绑定、派生、发布与修改拒绝 | 本人或管理员恢复；管理员永久删除 |
| 单产物 | 从产物和资料归档隐藏，下载拒绝；正常请求评分比较不受影响 | 管理员恢复或永久删除；既有保留期继续，到期后标记不可恢复 |

回收站只展示管理所需的最小身份、范围与状态。回收父对象会包含已回收子版本，旧子事件暂不可操作；恢复父对象还原之前各子状态。恢复再回收生成新的唯一事件，旧事件不能删除新事件。永久删除使用事件 ID 与独立幂等键，进入删除后只保留墓碑和最小操作回执，同键换事件冲突。旧 accepted/rejected/附件回执都不能复活内容，不同请求正文仍冲突。

准备流程仍依赖目录 bundle 或父实验目录时，先关闭读取权限，标记待清理，准备完成后以同一事件和键重试永久删除。安全下载先在锁内取得完整独立文件快照，再传输，清理不会交付残缺归档。物理清理失败不伪报已完成，重试不会换删除范围。备份与其他正常请求的独立冻结副本不属于本次清理范围。

## 附件下载

任何团队成员可下载指定附件版本，包含且仅包含该版本目录内容，不限上传者。停用版本仍可下载，回收版本不可下载；内容完整性和安全检查失败拒绝归档。网页提供版本下载链接，CLI 为 `attachments download VERSION --output NEW.zip`，SDK 为 `fetch_attachment`，MCP 同名工具受固定下载根限制。

## 自动化入口

PAT 继续以有效成员身份执行旧操作；新增的当前 `account_role` 只参与管理权限。旧 PAT 不自动扩权，`read`/`attachments` 不隐含下载或回收。新 scope 为 `attachment_download`、`recycle_own`、管理员专用 `datasets_manage`/`recycle_all`/`purge`。永久删除还需对应对象的回收管理资格，单独 purge 不能枚举全站或清理任意对象。evidence 资格独立。

HTTP 前缀 `/api/v1/management`：`GET /requests`、`PATCH /groups/{id}`、`GET /datasets`、`GET /datasets/{id}/versions`、`POST /datasets/{id}/preview`、`POST /datasets/confirm`、`PUT /datasets/{id}/default`、`POST /dataset-merge/preview`、`POST /dataset-merge`、`GET /recycle`、`POST /recycle/preview`、`POST /recycle`、`POST /recycle/{event}/restore`、`POST /recycle/{event}/purge`。下载为 `/api/v1/attachment-versions/{id}/download`。参数检查/保存沿用 `/api/v1/admin/datasets/{id}/author-inputs[/check]`，带 `version_id`。

CLI `manage --help` 列出 register-dataset、requests、rename-group、datasets、versions、preview、confirm、default、parameters-check/save、merge-preview/merge、recycle-preview/recycle、recycle-list、restore 和 purge。`submit` 支持 `--dataset-id`、`--dataset-source-version-id`、`--source-request-id` 和 `--independent`。例如：

```bash
harbor-helper manage register-dataset Bench team/bench
harbor-helper manage versions DATASET
harbor-helper manage preview DATASET sha256:DIGEST
harbor-helper manage confirm PREVIEW
harbor-helper manage recycle-preview attachment_version VERSION
harbor-helper manage recycle --items '[{"kind":"attachment_version","object_id":"VERSION"}]'
harbor-helper manage restore EVENT
harbor-helper manage purge EVENT --idempotency-key UNIQUE_KEY
```

SDK 提供对应的 `register_dataset`、`list_requests`、`rename_group`、`dataset_versions`、`preview_dataset`、`confirm_dataset`、`set_dataset_default`、`check_dataset_parameters`、`save_dataset_parameters`、`merge_datasets_preview`、`merge_datasets`、`preview_recycle`、`recycle`、`restore`、`purge`。MCP 提供同等工具（默认选择为 `dataset_default`，参数为 `dataset_parameters`），独立 `purge` 工具标注破坏性；提示不替代后端鉴权。具体类型、错误与有效能力由运行时 machine schema/discovery 返回。
