# 维护者与成员验收

## 维护者一次准备

在统一机器上按 [README](../README.md) 安装，准备已验证 runtime、Harbor Hub 权限，并初始化共享 state。提供给成员的入口为：

```bash
cd /path/to/harbor-helper
export HARBOR_HELPER_STATE=/path/to/team
.venv/bin/harbor-helper doctor
```

`doctor` 的整体 `ok=true` 表示默认 oracle 必需条件就绪；没有配置模型时，model 检查可提示可选能力未验证。所有成员使用同一 state 和受信任的共享账号，不自行 init。机器复查完成后再交付成员使用。

真实模型 A10 另需维护者在共享 `team.json` 配置 endpoint、served model ID、声明 checkpoint 版本、固定 opencode 版本和可选凭据环境变量名，格式见 README。凭据通过受保护渠道设置，不发到群里或写入配置、命令参数、验收反馈。更新凭据环境前等待所有任务终止，执行 stop，再在正确环境执行 recover。

```bash
.venv/bin/harbor-helper doctor --preset model
.venv/bin/harbor-helper submit --preset model --task generation--box
```

保留返回的真实 run ID；结束后用 status/report 查看原始模型执行与 verifier 证据。doctor 不发模型请求，必须实际提交才能验证 A10。不要求模型必然得高分；须能区分正常低分与接入/执行故障。由 checker 核对真实路径中的凭据处理限制，补齐 A9 模型部分。

## 未参与搭建成员的操作

请一位未参与实现或机器测试的成员自行执行；维护者预先配置环境，过程中不代改脚本。首次 SSH 登录后运行上述入口命令。

1. 提交默认两题实验，保存返回的 run ID，随后主动断开 SSH：

   ```bash
   .venv/bin/harbor-helper submit
   exit
   ```

2. 重新 SSH 登录，重新运行 `cd` 和 `export`。将下方 `hh-实际基线ID` 换成第一步返回的 ID：

   ```bash
   BASE_RUN=hh-实际基线ID
   .venv/bin/harbor-helper status "$BASE_RUN"
   .venv/bin/harbor-helper logs "$BASE_RUN"
   .venv/bin/harbor-helper report "$BASE_RUN"
   ```

   若仍 queued/running，稍后再查看。预期原实验继续执行，最终 succeeded，报告包含两题有效评分与证据路径；失败则记录原因，不视作通过。

3. 使用随项目提供的 bundle 提交候选，保存新的 ID。候选使用同一数据集和默认条件：

   ```bash
   .venv/bin/harbor-helper submit --bundle examples/bundle-probe
   CANDIDATE_RUN=hh-实际候选ID
   .venv/bin/harbor-helper status "$CANDIDATE_RUN"
   .venv/bin/harbor-helper report "$CANDIDATE_RUN"
   ```

   候选结束后对比，预期 comparable=true，显示 bundle 摘要变化和逐题 delta。oracle 候选得分相同、delta=0 也满足此项。此 bundle 用于验证准备内容被消费，不证明真实模型利用技能。

   ```bash
   .venv/bin/harbor-helper compare "$BASE_RUN" "$CANDIDATE_RUN"
   ```

4. 整体重跑候选，保存返回的新 ID。结束后报告并对比；预期新记录独立、原报告仍可查询、固定输入可比：

   ```bash
   .venv/bin/harbor-helper rerun "$CANDIDATE_RUN"
   RERUN_RUN=hh-实际重跑ID
   .venv/bin/harbor-helper status "$RERUN_RUN"
   .venv/bin/harbor-helper report "$RERUN_RUN"
   .venv/bin/harbor-helper compare "$CANDIDATE_RUN" "$RERUN_RUN"
   .venv/bin/harbor-helper report "$CANDIDATE_RUN"
   ```

## 返回验收反馈

反馈成员是否参与搭建、产品 commit、基线/候选/重跑三个 ID、断开重连后结果、对比是否可比，以及遇到的说明或命令障碍。只需报告结论及不含秘密的错误摘要；不上传带凭据的原始配置或日志。

成员自行完成上述操作且无维护者代改脚本，才能判 A11 通过。A10 可以由维护者完成，A11 可以先用 oracle 完成，两者各自保留结论。
