# 真人成员使用验收

请一位未参与搭建或机器测试的成员，按照 [README](../README.md) 自行完成日常操作，记录说明是否足够清楚。维护者提前准备环境，试用时不代改脚本。

这与真人使用验收分别记录。用户已反馈 API key 注入不清楚、默认提交误认为模型实验，以及 README 细节过多；这些是本轮需要修正的使用问题，尚不能据此将真人验收标为通过。命令输出美化另列后续任务。

## 准备入口

已有团队环境的成员使用同一个 state，不再次执行 `init`。新机器安装、模型配置与 API key 文件准备见 [配置指南](configuration.md)；日常任务、候选对比和故障处理见 [操作指南](operations.md)。

```bash
cd /path/to/harbor-helper
export HARBOR_HELPER_STATE=/path/to/team
.venv/bin/harbor-helper doctor
```

`doctor` 检查环境和配置，不发送模型请求，也不验证模型认证成功。真实模型实验请按 README 的文件凭据包装入口运行，并显式指定 `--preset model`。带凭据的入口也用于可能重新启动后台调度器的 `recover`、`status`、`list` 和 `rerun`。

下面使用 oracle 自检来验收提交、断开重连与候选对比，无需 API key 或付费模型调用。oracle 执行题目自带解答，不能证明模型解题或使用候选技能。请在维护者确认团队无其他任务时进行；不要在模型任务运行中刷新或停止调度器。

## 自行完成一次操作流程

1. 显式提交 oracle 基线，保存返回的 run ID，随后主动断开 SSH：

   ```bash
   .venv/bin/harbor-helper submit --agent oracle
   exit
   ```

2. 重新 SSH 登录，重新运行上面的 `cd` 和 `export`。将占位 ID 换成第一步返回的 ID：

   ```bash
   BASE_RUN=hh-实际基线ID
   .venv/bin/harbor-helper status "$BASE_RUN"
   .venv/bin/harbor-helper logs "$BASE_RUN"
   .venv/bin/harbor-helper report "$BASE_RUN"
   ```

   如果仍在排队或运行，稍后再查看。预期原实验继续执行，最终报告包含两题有效评分与证据路径。

3. 使用项目提供的 bundle 提交 oracle 候选，保存新 ID：

   ```bash
   .venv/bin/harbor-helper submit --agent oracle --bundle examples/bundle-probe
   CANDIDATE_RUN=hh-实际候选ID
   .venv/bin/harbor-helper status "$CANDIDATE_RUN"
   .venv/bin/harbor-helper report "$CANDIDATE_RUN"
   ```

   候选结束后对比：

   ```bash
   .venv/bin/harbor-helper compare "$BASE_RUN" "$CANDIDATE_RUN"
   ```

   预期 `comparable=true`，显示 bundle 摘要变化和逐题分数差。oracle 分数相同也满足使用流程验收；此 bundle 只用于确认准备内容被消费。

4. 整体重跑候选，保存返回的新 ID。结束后查询报告与对比：

   ```bash
   .venv/bin/harbor-helper rerun "$CANDIDATE_RUN"
   RERUN_RUN=hh-实际重跑ID
   .venv/bin/harbor-helper status "$RERUN_RUN"
   .venv/bin/harbor-helper report "$RERUN_RUN"
   .venv/bin/harbor-helper compare "$CANDIDATE_RUN" "$RERUN_RUN"
   .venv/bin/harbor-helper report "$CANDIDATE_RUN"
   ```

   预期产生独立记录，原报告仍可查询，固定输入可比。`rerun` 会再次执行任务；此处重跑的是 oracle 候选。

## 返回反馈

反馈是否参与搭建、产品 commit、基线/候选/重跑三个 ID、断开重连后的结果、对比是否可比，以及遇到的文档或命令障碍。只需安全错误摘要，不发送 API key 或带秘密的原始日志。

成员自行完成上述流程、无维护者代改脚本，且使用问题得到确认，才能判真人使用验收（A11）通过。模型链路验收（A9/A10）已通过，本轮文档检查无需另发模型请求。
