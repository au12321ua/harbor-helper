# 数据集切换最小示例

Harbor Hub 私有数据集 `au12321ua/harbor-helper-switch-smoke@1`，含一个非 CAD 任务：向 `/app/answer.txt` 写入固定文本。oracle 解答和 Python 校验均不依赖网络或模型，评分为精确匹配的 0/1。Dockerfile 固定现有 Python 3.12 镜像 digest。

项目目录下使用已有团队配置，无需重新 init：

```bash
.venv/bin/harbor-helper submit --dataset au12321ua/harbor-helper-switch-smoke@1 --agent oracle
```

`--dataset` 只覆盖本次提交；team.json 默认值不变。后续不带该参数的 submit 继续用默认数据集，rerun 保留原任务快照。此包默认私有，其他账号需 Hub 访问权限。

数据集与任务使用 Harbor 原生格式。维护者复现发布：

```bash
.venv/bin/harbor publish examples/harbor-helper-switch-smoke --private --concurrency 1
```

这条命令会写入 Hub；仅在确实需要发布时运行。它不创建模型请求。该示例验证选择、下载和执行链路，不用于评估模型能力。
