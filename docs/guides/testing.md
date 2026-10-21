# 测试维护约定

测试按行为与执行边界组织。新增或调整测试先确定要保护的用户行为、失败风险和最小必要执行层次，不以用例数量或文件行数作为覆盖目标。

## 选择验证层次

| 入口 | 适用范围 |
| --- | --- |
| `uv run pytest -q` | 默认排除 `browser`，运行无需 Chromium 的 Python 自动测试；不是完整门禁。 |
| `python3 scripts/verify.py --mode backend …` | 隔离运行 Python、契约与三项静态检查，显式 `-m 'not browser'`，不允许 skip。 |
| `python3 scripts/verify.py --mode full …` | 隔离运行全部 Python、真实生产页面浏览器探针、前端类型/lint/build 和 Playwright mock UI；不允许 skip/xfail/only/空集合。 |
| `cd frontend && npm run test:ui` | 日常定向调试拦截 API 的页面行为；正式验证由 full 读取机器报告。 |

依赖、Python 版本组合、命令参数、隔离和 CI 见[自动化验证](automation-ops-ci.md)。定向 pytest 可以用 `-k`/节点 ID，但统一门禁不依赖具体测试函数名。直接运行测试前同样必须隔离 HOME/state、清除真实凭据、禁用真实 Docker socket；优先使用 verify 的白名单环境，不能拿团队 state 或真实模型作 fixture。

## 布局与复用

Python 的 `tests/conftest.py` 集中注册 function-scoped fixture。`service_support` 提供账户、加密假 key 与来源准备 factory；`process_support`/`http_support` 管理真实隔离进程、等待、HTTP 与回收；`core_support` 提供 oracle run/report 构造；附件、恢复、automation 和 ops 构造各在相应 `*_support.py`。已有 `admission_fixture`、`scheduler_support`、`protocol_server` 继续承担原来的支持职责。`protocol_wire.py` 仍是显式手工选择的独立 wire 检查，不进入默认收集。

测试只从支持模块导入 helper；fixture 通过参数请求，不从其他 `test_*.py` 导入，也不调用 pytest 私有解包 API。pytest 的 `pythonpath` 显式包含 `tests` 与 `scripts`。需要在测试中直接构造另一实例时调用公开 factory，每次使用新的 tmp_path 子目录和明确的 MonkeyPatch 上下文；不要直接调用 fixture。复用构造过程，不共享可变账户、目录、HTTP client 或 catalog。局部特有场景保留局部 fixture，不为消除几行重复建立通用框架。

`test_results`、`test_run_configuration` 与 `test_scheduler` 分别覆盖结果、冻结配置和调度；`test_sdk_mcp` 保留公开入口的真实进程集成，`test_operation_history`/`test_evidence_workflow` 覆盖各自业务边界。纯领域测试使用 synthetic activity；真实 HTTP、scheduler、worker 与 CLI/MCP 的集成测试继续启动隔离进程，只替换外部 Hub/Docker/模型边界，不能统一改成 mock。

Playwright 的 `qa/*.spec.ts` 按配置、提交、工作台、权限、附件、历史资料、主题和更新组织；`fixture.ts` 提供场景默认数据，`ui-support.ts` 复用目录刷新 barrier 和工作台构造。修改 mock 数据时克隆每次测试的状态，避免修改导出模板。

## API mock 必须封闭

所有 spec 从 `./fixture` 导入扩展的 `test`，不能绕回 Playwright 原始 `test`。auto fixture 在 context 层拦截 `**/api/**`，对未注册的方法与路径记录错误并中止请求，teardown 统一断言无未知请求；即使 UI 吞掉异常，测试也必须失败。额外创建的移动 context 必须调用 `fixture(page)` 安装同一保护，并在测试内关闭。

公共外壳读取接口提供符合 DTO 的缺省值；通用业务路由按方法和路径明确匹配。场景自定义的 page route 优先于基础路由，未处理的请求用 `route.fallback()` 交给保护层。故意错误、断连、畸形响应必须在场景中显式注册，不能加入“允许未知”的白名单，也不能用 `/admin/*`、任意 `/logs` 或空成功对象兜底。新增 DTO 有类型导出时用 `satisfies` 约束默认响应。

## 生产页面接线与执行证据

真实页面用例标记 `@pytest.mark.browser`，通过 `browser_support.run_browser(request, script, env=…)` 启动 Node。helper 验证标记，等待子进程成功后才记录脚本路径；失败、超时和未标记调用都不能生成成功证据。普通 pytest 排除该层，full 显式覆盖默认选择，无环境变量可以把它转为 skip。

full 先收集 pytest 节点，再核对实际 setup/call/teardown 全部 passed，要求 browser 集合非空；成功脚本集合必须等于 `qa/*-production.mjs` 排除手工脚本后的集合。新增生产探针沿用该命名并接入 helper，不维护函数名清单或历史测试数量下限。Playwright 开启 `forbidOnly`；full 比对收集与实际报告的项目/节点身份，拒绝空集合、skip/fixme、失败、flaky 和未执行项。

| 脚本 | 归类 |
| --- | --- |
| `automation-production.mjs` | 自动 browser：凭证页面与真实 HTTP 接线。 |
| `admission-production.mjs` | 自动 browser：受理、维护与额度。 |
| `damaged-observation-production.mjs` | 自动 browser：损坏记录的局部观察与安全。 |
| `reuse-export-production.mjs` | 自动 browser：复用、导出及冻结来源。 |
| `theme-production.mjs` | 自动 browser：首次设置、首屏主题、跨标签同步和生产页面；fresh state，无真实实验。 |
| `live-service.mjs` | 维持手工，不计入自动覆盖。 |
| `final-integration-production.mjs` | 维持手工，不计入自动覆盖。 |

## 断言、等待与删除

断言可观察结果和重要的负面行为：身份权限、秘密不泄漏、持久幂等、取消与恢复、释放和审计的区别，以及零分/缺评分/失败。UI 优先 role、label、可见结果与实际请求内容。常量可以是有效的边界、协议版本、非法输入或安全哨兵，不机械删除。不要固定 UUID 的生成布局、长期测试总数或无契约的内部排序；时长断言优先比较同一业务事件的时间字段。异步行为用事件、barrier、终态、HTTP 完成和浏览器渲染机会等待，不用任意 sleep 猜进度；验证“某时间窗内不能发生”的等待需说明窗口依据。

删除/合并按断言组审查：写明原意图、为什么无独立价值、替代覆盖的测试位置，或证明被保护行为已不存在。不同前置状态、角色、入口和状态变化前后的相似断言通常不能合并。产品分支仍在时，不能因“兼容不保证”删除 legacy/old 命名用例中的安全与恢复检查。

较大治理改动先保留固定基线的收集清单，再依次提交门禁、公共组件、断言改写/删除、纯移动拆分和文档。为更名、参数化、合并、删除保留节点映射；纯拆分比较函数 AST/场景内容。抽查关键保护时用局部故障注入验证能失败，不能只证明原有测试还通过。现场材料与原始输出留在主仓 ignored `.local/`；报告注明提交、隔离条件、实际命令、耗时与未覆盖边界。真实 Hub/Docker/模型、手工脚本及部署环境需单独授权和验证。
