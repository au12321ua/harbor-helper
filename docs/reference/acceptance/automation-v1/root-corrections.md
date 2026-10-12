# Root 两项修正工程报告

修正父候选：`34f3bafd0faf7b1cd93adc14f371a5f9d3cedfa5`。本轮实现及静态产物固定版本：`bad020357104dc72bed7c955ae5dc16d0c2e104f`。本报告与日志在后续仅文档提交归档，不改变该实现对象；最终远端候选 SHA 由交付回报明确。仅 Engineer 自查，待 Root 复核与 Checker 独立验收。

## 修正及覆盖

- CLI HTTP 错误 JSON 为 list/null/string 时统一抛安全 `RemoteError`，没有本地执行回退。action 只接受非空字符串，先用既有秘密脱敏，再截取最多 128 字符；无效类型不显示。新增非对象响应、action 类型/长度/原值脱敏回归。
- 凭证到期取消 366 天服务上限和 365 天网页上限，保留默认 30 天。服务只接受数值、有限、严格未来的 Unix 秒；bool、字符串、NaN、正负无穷、溢出整数、当前/过去时间均拒绝。未来极短时间、730 天成功；730 天凭证实际通过 API 认证。网页允许正整数天数且无年度最大值，730 天签发 fixture 回归通过。接口文档一致。
- 重新构建静态页面，源组件与打包产物一起提交。

## 实际执行与证据

独立 HOME `/tmp/hh-automation-validation/home`，`env -i` 清除继承配置；Python 测试仅 fake 身份/独立临时 state，UI 拦截 API fixture。不操作正式服务/state/镜像。

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `.venv/bin/python -m pytest -q tests/test_service_cli.py tests/test_automation.py` | 52 passed；1 条现有 Starlette/httpx 弃用提示 | [python.log](root-corrections-logs/python.log) |
| `npm run test:ui -- --grep "automation credential"` | 1 passed | [ui.log](root-corrections-logs/ui.log) |
| `npm run build` | 通过 | [build.log](root-corrections-logs/build.log) |
| `npm run lint` | 通过 | [lint.log](root-corrections-logs/lint.log) |
| `.venv/bin/ruff check src tests` | 通过 | [ruff.log](root-corrections-logs/ruff.log) |
| `git diff --check` | 通过 | [diff-check.log](root-corrections-logs/diff-check.log) |

安全日志逐份 SHA256/字节数见 [本轮索引](root-corrections-log-index.json)。本轮无失败测试，无删除/弱化必要断言。

## 版本、未覆盖及回退

原 [d46/34f3 工程报告](engineering-report.md)及12份日志保持逐字不变，原通过范围仅限原版本。本轮没有重新执行全量292 Python/28 UI、生产浏览器HTTP或CLI执行闭环；没有 Docker/Hub/付费模型调用，不能把历史结果直接宣称为新候选独立PASS。两份附件原文及其 PARTIAL/限定补PASS范围保持不变。

无持久层迁移、无新表/历史记录改写、无外部接口新端点；API仅放宽有效未来到期，错误显示恢复安全边界。回退本修正会重新引入非对象错误异常和年度上限；已签发的长期凭证在既有认证逻辑仍按自身 expires 判断。不应因回退删除凭证、幂等记录或正式state。完整既有迁移/回退限制仍见 [API说明](../../automation-api.md)。未改 dev/master/部署树。
