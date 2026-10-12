# 原执行命令与实际加载边界

候选 worktree/HEAD：`/tmp/hh-checker-automation-v1-50b0dde` / `50b0dde46d66bd509fed3fe56eb749919779968c`。

54 项最终重跑使用原命令：

```sh
env -i PATH=/home/pc/.nvm/versions/node/v22.23.1/bin:/home/pc/.local/bin:/usr/local/bin:/usr/bin:/bin HOME=/tmp/hh-checker-automation-v1-50b0dde/home PYTHONPATH=/tmp/hh-checker-automation-v1-50b0dde/src PLAYWRIGHT_BROWSERS_PATH=/home/pc/.cache/ms-playwright HH_TEST_BROWSER=1 PYTEST_ADDOPTS='-p no:cacheprovider' /tmp/hh-automation-api-v1/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_automation.py tests/test_automation_http.py tests/test_service_cli.py
```

`env -i` 白名单只有 `PATH`、`HOME`、`PYTHONPATH`、`PLAYWRIGHT_BROWSERS_PATH`、`HH_TEST_BROWSER`、`PYTEST_ADDOPTS`。`PYTHONPATH` 指向固定候选 worktree 的 `src`；pytest 的测试文件也从该 worktree 执行。工程树 `/tmp/hh-automation-api-v1/.venv` 与 `frontend/node_modules` 只读复用；Node 22.23.1 在 PATH 首位。浏览器依赖通过本 worktree 下临时 symlink 指向既有 `node_modules`，测试后已移除。Pytest fixture 的 worker 在临时复制包 cwd 运行，source/worker adapter 为测试 fixture。

首次运行用 Node 18.19.1，输出显示 `ERR_MODULE_NOT_FOUND: Cannot find package '@playwright/test'`，退出码 1（其他 53 项通过）。修正只涉及验证环境：PATH 改为 Node 22 并补临时依赖链接；随后单独浏览器用例退出码 0，再以修正环境重跑上述同一命令，54 passed。测试生成的临时 state/master/profile 及 pytest 根目录已清理，未保留 state 或 master 值。

## 保存方式与未保留项

这些文件保存本轮会话中 `functions.exec` / `functions.write_stdin` 可见的输出片段及退出状态；54 项与浏览器重试输出按 tool response chunk 复制。初次失败 traceback 的 `CompletedProcess` 摘要是可见 tool output 中 pytest 截短后的行。它们不是进程当时重定向保存的原始字节流。原运行时没有写入 stdout 日志文件；本补充没有重跑命令。54 项通过输出由当时两段 streamed tool output 组成，按 chunk 分文件保存。Node 依赖失败和迁移 JSON 同样是原 tool output。其它未列出的 stdout/stderr 字节、PTY/进程环境快照没有保留。
