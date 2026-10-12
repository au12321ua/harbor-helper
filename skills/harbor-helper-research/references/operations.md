# v1 薄 CLI 与 HTTP 操作

以下占位符用发现结果替换；`research` 是示例 profile。所有例子都调用团队服务，安装 CLI 依赖与目标服务兼容，不能用本地 auth login 注入团队 key。

## 连接与发现

```bash
harbor-helper service configure-token --url https://YOUR_SERVICE --token-file /private/access-token --profile research --json
# 或从现有安全文件读取 stdin（不在命令里写原值）
harbor-helper service configure-token --url https://YOUR_SERVICE --token-stdin --profile research --json < /private/access-token
harbor-helper --remote-profile research service status --json
harbor-helper --remote-profile research service schema --json
harbor-helper --remote-profile research service discover --json
harbor-helper --remote-profile research service tasks DATASET_ID --offset 0 --limit 20 --json
```

status 返回已认证 `/me` 身份；schema/discovery/tasks 需要 read。任务切片 limit 1–100；使用返回 next_offset 续读，null 结束。PAT 默认 read；提交和 lookup 需要 execute，取消需要 cancel_own；execute 不隐含 read。

## 三个新 submit

示例为**已有授权和预算**的同条件模型实验；选择团队 MODEL_PROFILE_ID，DATASET_REFERENCE 用已发现的固定 reference，不把 DATASET_ID 填给 CLI `--dataset`。CLI 目前没有 `--dataset-id` 和环境构建倍率参数，需要这些字段时用 HTTP。`--task` 是任务名 glob，省略会选择整个数据集。以下示例数值只是待按授权替换的研究输入，不是预算保证。

```bash
harbor-helper --remote-profile research submit --dataset DATASET_REFERENCE --model-profile MODEL_PROFILE_ID --task TASK_GLOB --attempts 1 --concurrency 1 --wall-seconds 120 --idempotency-key STUDY-baseline --json
# 完成保全与未知响应恢复后再开始下一次写
harbor-helper --remote-profile research submit --dataset DATASET_REFERENCE --model-profile MODEL_PROFILE_ID --task TASK_GLOB --attempts 1 --concurrency 1 --wall-seconds 120 --attachment-version-id V1_ID --idempotency-key STUDY-v1 --json
harbor-helper --remote-profile research submit --dataset DATASET_REFERENCE --model-profile MODEL_PROFILE_ID --task TASK_GLOB --attempts 1 --concurrency 1 --wall-seconds 120 --attachment-version-id V2_ID --idempotency-key STUDY-v2 --json
```

仅隔离验证且明确选择 Oracle 时改用 `--agent oracle` 代替模型方案；不把 Oracle 分数当模型效果。

提交前在用户私有操作记录中保存确切正文（由 CLI 字段映射形成）：dataset、model_profile、task、attempts、concurrency、wall_seconds，候选另有 attachment_version_id。例子中的固定类别均为 submit、路径 `/submissions`，无附件正文不含附件字段。CLI 发请求前还自动写 `~/.config/harbor-helper/remote/receipt-research.json`（0600）。**每次写返回/失败后、下一次写前**复制该 receipt 到本次研究独立私有目录，保全其原 path/body/user_id/idempotency_key/url；给记录补固定类别与授权范围。不得复制 profiles 中含 token 的文件、整包 remote 目录或把记录放附件。并行操作优先各自保存 HTTP 请求记录，不能共用最近 receipt 恢复。

```bash
harbor-helper --remote-profile research service lookup submit STUDY-baseline --json
harbor-helper --remote-profile research service retry --json
harbor-helper --remote-profile research service query sub-RECEIPT --json
harbor-helper --remote-profile research service query hh-RUN --json
harbor-helper --remote-profile research service report hh-RUN --json
harbor-helper --remote-profile research compare hh-BASELINE hh-V1 --json
harbor-helper --remote-profile research compare hh-V1 hh-V2 --json
harbor-helper --remote-profile research cancel sub-OWN_RECEIPT --json
harbor-helper --remote-profile research cancel hh-OWN_RUN --json
```

service retry 仅在**最近 receipt 就是待恢复操作**时使用；其他记录用其原请求重发。compare 通过兼容 `/compare` 返回机器安全投影；comparable=false 时 CLI 退出 2，仍应读取输出 reasons。取消请求成功不代表资源已释放，继续查三轴。

## 直接 HTTP（CLI 未暴露字段时）

使用安全文件在进程内读取 PAT，构造 Authorization Bearer header；写请求含 `X-Requested-With: harbor-helper`。不使用会把 bearer 展开进 argv 的 `curl -H` 命令，不输出 header，不跟随跨站重定向。保存操作记录后才发 POST；没有秘密的输出仍须按安全报告解读。完整 schema 从目标服务读取，此处只列研究路径：

| 操作 | `/api/v1` 下的方法与路径 |
| --- | --- |
| 身份/发现 | GET `/me`、`/machine/schema`、`/machine/discovery`、`/readiness` |
| 任务切片 | GET `/machine/datasets/{id}/tasks?offset=0&limit=20` |
| 新提交 | POST `/submissions`，header `Idempotency-Key: 原键` |
| 找回 | GET `/submission-operations/{submit\|rerun\|retry\|recover}/{原键}`（URL 编码键） |
| 状态/安全报告 | GET `/machine/submissions/{id}`、`/machine/runs/{id}`、`/machine/runs/{id}/report` |
| 比较 | POST `/machine/compare`，正文 `{"left":"hh-LEFT","right":"hh-RIGHT"}` |
| 取消本人记录 | POST `/submissions/{id}/cancel` 或 `/runs/{id}/cancel`，正文 `{}` |

新提交正文示例（占位符按发现/授权替换，无附件省略 attachment_version_id；其余条件保持）：

```json
{"dataset_id":"DATASET_ID","model_profile":"MODEL_PROFILE_ID","task":"VERIFIED_TASK_NAME","attempts":1,"concurrency":1,"wall_seconds":120,"environment_build_timeout_multiplier":1,"attachment_version_id":"V1_ID"}
```

使用 dataset_id 时 task 选已验证目录里的确切任务名；显式 dataset reference 的 CLI task 可用 glob。

HTTP 错误读取 code/action/request_id/related_ids/poll_after_seconds/wait_known，不记录原始网络诊断。retry_same_request 重发原请求；poll_existing 查已有记录；fix_input 修正误输与调查冲突；reauthorize 停止该操作待重新授权；contact_admin 呈现安全原因；explicit_new_attempt 不代表自动获准新实验。普通主动 rerun/retry/recover 使用新键并保持原附件；详细输入读 schema。

`service discover` 返回 readiness 与 pending（若目标契约支持）；`accepting` 仅为初始化/维护/scheduler 活动门，不保留容量。503 maintenance_paused/scheduler_unready、429 member_queue_full/queue_full 用原键有限重试或查旧受理，等待未知时不要提供预计开始时间，也不要切换 PAT/成员绕过限额。匿名 health 不含维护原因；管理员配置只能通过获授权浏览器会话，管理员 PAT 也不能暂停/恢复服务。
