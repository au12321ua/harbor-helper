# 维护与调度器数值边界修正工程报告

基线 `54b6df23569dbdb38381c50f9044938dcd16222f`；修正产品与测试固定 `b5c409b20ba8cfe8bf3a7d7e37525ca4b7ff0c3c`，分支 `feature/member-admission-maintenance`。本报告仅证明下面列出的工程自查，待Root差分审查及Checker独立验收。

## 修正与兼容

`admission.finite_number`统一精确int/float类型及有限浮点可表示性校验，捕获OverflowError；维护请求、持久retry_at/updated及scheduler heartbeat复用。bool/NaN/正负inf/正负10**400拒绝，不设年度或任意数字上限；10**300请求与读取保留，未来heartbeat仍unknown。无效请求返回maintenance_retry/422；损坏持久字段返回admission_state_unavailable/503，匿名health ready=false且新受理拒绝；损坏heartbeat unknown/unready且新受理scheduler_unready/503，成功旧幂等键仍找回。无前端/static/schema/配置格式、历史manifest、密钥或持久数据迁移。

回退只涉及代码，无需迁移；回退会重新暴露超大整数边界异常。损坏维护状态未自动覆盖/删除，不通过重启开放受理；恢复须在受控维护流程纠正损坏值并保留原state及外master。

## 实际验证

所有命令在独立树/tmp/hh-admission-maintenance，用run-check.py白名单环境，独立HOME/Harbor profile/XDG；pytest TemporaryDirectory state与state外dummy master，假凭证，无真实模型请求。scheduler fixture显式synthetic birth/heartbeat，不声称真实scheduler执行或生产HTTP排空。

- before: `.venv/bin/python -m pytest -q tests/test_admission_numbers.py`，退出1，8 failed/17 passed；产品基线54b6df，测试新文件。失败均正负超大整数，完整原stdout/stderr保留。
- focused: `.venv/bin/python -m pytest -q tests/test_admission_numbers.py tests/test_admission.py`，退出0，35 passed；修复后未提交工作树。
- ruff: `.venv/bin/ruff check src tests`，退出1；新增测试导入fixture同名导致F811，随后改为alias加本地fixture，未改断言。
- ruff-final/product-diff: 退出0；未提交工作树。
- fixed-focused: 上述两测试文件，固定b5c409b，退出0，35 passed/1依赖弃用提示。
- fixed-ruff: `.venv/bin/ruff check src tests`，固定b5c409b，退出0。
- fixed-diff: `git diff --check 54b6df HEAD`，固定b5c409b，退出0。

25个新参数化专项覆盖请求、两种持久字段、scheduler、安全健康与受理守门以及原键保全；另10个原受理专项必要回归。此前327Python/29UI/build结论只属于原7b77f5f产品，不扩大到本次版本；本次按授权不重跑全量/UI/build。未做Hub/Docker/模型/正式升级/全局清理，未操作部署树/真实state/外master/镜像。

## 保护与证据

修正diff仅两个服务端文件与新测试；frontend/static/锁/既有报告日志不变。实时远端dev仍0b05daf92c8478f990af46e6edf45a6b10abb60f，master仍9451363155674f138123c94c5e1ba51687139b36。旧工程报告SHA58270234f0ebda6577e5f717d373f30dad910306675357b686c4fc9c3fc01fd6、前项skill逐字原报告SHAcc9b5a6d5b844d2f11983340f1d1859364388b3c4fa03e384f0c20774b65f683复核不变。

capture目录保存每次完整合并stdout/stderr与.exit原件，包括两次失败；run-check.py为实际隔离执行器，evidence-sha256.json逐文件字节及SHA索引。无state/主密钥/PAT上传。原失败日志保留空白，不清理traceback，因此包含capture的全diff-check可能报告空白；产品diff检查通过。

版本日志：b5c409b修正数值判断与专项；随后证据提交只归档本报告/隔离runner/原输出/SHA。未完成项：Root固定差分审查与Checker独立验收，非工程遗漏；不得据此宣称阶段已验收。
