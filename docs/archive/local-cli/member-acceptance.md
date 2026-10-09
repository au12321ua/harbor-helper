# 真人成员使用验收

请一位未参与搭建或机器测试的成员，按[本地CLI指南](../../guides/local-cli.md)自行使用正式CLI，记录是否开箱可用。维护者提前准备环境，试用时不代改脚本，也不要求成员定义辅助函数或拼接凭据注入。

机器行为验收与真人试用分别记录，fixture或机器人检查不能替代成员体验。

真实模型试验需记录固定产品版本、原评分、失败与费用/模型身份未知项，不能替代登录生命周期或真人试用。

用户指出前轮文档修正没有解决产品可用性，已授权用代码封装一次登录、普通提交、观测及停止/恢复/扫描。本页按 [原生入口设计](usability-design.md) 验收，不再沿用用户 shell 包装流程。

## 一次登录与重连

已有团队环境不重复 `init`。安装和模型配置见 [配置指南](../../guides/local-configuration.md)，日常命令见 [操作指南](../../guides/local-operations.md)。从已部署项目目录进入；登录在输入前显示所选 team 和模型服务：

```bash
cd /path/to/harbor-helper
.venv/bin/harbor-helper auth login
.venv/bin/harbor-helper auth status
```

`auth login` 隐藏输入 key，默认本地执行授权 8 小时。已有保护文件可用 `auth login --key-file /absolute/path/to/key`；自定义 team 在首次命令前指定 `--state /absolute/path/to/team`。登录记住 team，后续普通命令不需要重复注入凭据。

登录和 `doctor` 都不发送模型请求，不证明服务认证可用。可以先登录、断开 SSH、重连后运行 `auth status` 和 `list`，确认所选团队与登录仍可用。不要在有未终态任务时轮换或 logout；到期阻止新模型执行，已有任务正常收尾。

## 提交、重连与结果观察

下面用显式 oracle 完成不付费的使用流程。oracle 使用题目自带解答，不能证明模型解题或使用候选技能。裸 `submit` 的新默认是模型；只有用户决定执行真实模型实验时才使用它。

1. 提交 oracle 基线，记下 run ID，随后主动断开 SSH：

   ```bash
   .venv/bin/harbor-helper submit --agent oracle
   exit
   ```

2. 重连后回到项目目录，直接查看，无需重新登录或定义函数：

   ```bash
   .venv/bin/harbor-helper list
   .venv/bin/harbor-helper status hh-实际基线ID
   .venv/bin/harbor-helper logs hh-实际基线ID
   .venv/bin/harbor-helper report hh-实际基线ID
   ```

   若仍排队或运行，稍后再查看。预期原任务继续执行，终态报告含有效评分和证据路径；默认输出便于阅读，`status hh-实际基线ID --json` 可取得原数据结构。

3. 使用提供的 bundle 提交 oracle 候选，记下新 ID。结束后查看并对比：

   ```bash
   .venv/bin/harbor-helper submit --agent oracle --bundle examples/bundle-probe
   .venv/bin/harbor-helper status hh-实际候选ID
   .venv/bin/harbor-helper report hh-实际候选ID
   .venv/bin/harbor-helper compare hh-实际基线ID hh-实际候选ID
   ```

   预期可比，显示 bundle 摘要变化和逐题差值。oracle 分数相同也满足此项；该 bundle 只确认准备内容被消费。

4. 确认要重新执行 oracle 候选后，整体重跑，记下新 ID并对比：

   ```bash
   .venv/bin/harbor-helper rerun hh-实际候选ID
   .venv/bin/harbor-helper status hh-实际重跑ID
   .venv/bin/harbor-helper report hh-实际重跑ID
   .venv/bin/harbor-helper compare hh-实际候选ID hh-实际重跑ID
   .venv/bin/harbor-helper report hh-实际候选ID
   ```

   新记录独立，原报告仍可查询，固定输入可比。模型任务的 rerun 会再次发请求，本步骤重跑的是 oracle。

## 返回反馈

反馈是否参与搭建、产品 commit、登录/重连是否直接可用、三个 run ID、对比结果与遇到的障碍。重点是能否只用 CLI 完成操作，不需要借 shell 函数或 Python 片段处理凭据、等待后台停止或扫描。只提供安全错误摘要，不发送 key 或带秘密的原始日志。

真人使用验收（A11）仍需成员自行完成并确认体验；机器人、多进程 fixture 和历史模型成功不能替代。需要模型体验时按本地CLI指南使用普通submit，预算由用户决定，本轮不会为了真人清单自动追加模型请求。
