"""Terminal presentation of public CLI results; JSON keeps the business payload."""

import json
from datetime import datetime
from time import time

from rich.console import Console
from rich.table import Table
from rich.text import Text

STATUS = {
    "queued": "排队中",
    "starting": "启动中",
    "running": "运行中",
    "cancelling": "正在取消",
    "cleanup_blocked": "收尾阻塞",
    "succeeded": "成功",
    "failed": "失败",
    "cancelled": "已取消",
}
LABELS = {
    "state": "团队目录",
    "config": "配置文件",
    "run_id": "运行 ID",
    "id": "运行 ID",
    "created": "提交时间",
    "started": "开始时间",
    "finished": "完成时间",
    "concurrency": "并发数",
    "parent": "原运行 ID",
    "evidence": "证据目录",
    "status": "状态",
    "reason": "说明",
    "endpoint": "模型服务",
    "source": "凭据来源",
    "valid": "登录可用",
    "logged_in": "已登录",
    "logged_out": "已退出登录",
    "expired": "已到期",
    "expires_at": "到期时间",
    "key_available": "凭据可读取",
    "endpoint_matches": "服务配置匹配",
    "authentication_verified": "已验证服务认证",
    "execution_revoked": "新执行资格已撤销",
    "historical_audit_retained": "保留历史审计来源",
    "audit_retained": "保留历史审计来源",
    "audit_sessions": "历史审计来源数",
    "audit_incomplete": "审计不完整",
    "audit_complete": "审计完整",
    "unavailable_sources": "不可用审计来源数",
    "files_scanned": "已扫描文件",
    "matched_files": "命中文件",
    "unreadable_files": "不可读文件",
    "clean": "扫描通过",
    "scheduler": "调度器",
    "stopped": "已确认停止",
    "detail": "说明",
    "next_command": "下一步",
}


def _display(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, dict):
        return "; ".join(f"{key}={_display(item)}" for key, item in value.items()) or "—"
    if isinstance(value, list):
        return "; ".join(_display(item) for item in value) or "—"
    return str(value)


def _timestamp(value):
    try:
        return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except (TypeError, ValueError, OSError, OverflowError):
        return _display(value)


def _status(value):
    return f"{STATUS.get(value, value)} ({value})" if value in STATUS else _display(value)


def _table(title, *columns):
    result = Table(title=title, title_justify="left", show_lines=False)
    for column in columns:
        result.add_column(column, overflow="fold")
    return result


def _fields(console, value, *, title=None, omit=()):
    rows = _table(title, "项目", "内容")
    for key, item in value.items():
        if key in omit:
            continue
        if key in {"expires_at", "created", "started", "finished"}:
            content = _timestamp(item)
        elif key == "status":
            content = _status(item)
        else:
            content = _display(item)
        rows.add_row(Text(LABELS.get(key, key)), Text(content))
    console.print(rows)


def _hint(console, command, run_id):
    console.print(f"{command}：harbor-helper {command} {run_id}", markup=False, highlight=False)


def _runs(console, values):
    if not values:
        console.print("还没有运行记录。使用 harbor-helper submit 提交任务。", markup=False)
        return
    rows = _table("运行记录", "运行 ID", "状态", "用时", "说明")
    for row in values:
        started, finished = row.get("started"), row.get("finished")
        elapsed = "—"
        if started is not None:
            seconds = max(0, (finished if finished is not None else time()) - started)
            elapsed = f"{seconds:.0f}s"
        rows.add_row(
            Text(str(row.get("id", row.get("run_id", "—")))),
            Text(_status(row.get("status"))),
            Text(elapsed),
            Text(_display(row.get("reason"))),
        )
    console.print(rows)
    console.print("查看详情：harbor-helper status <run-id>", markup=False)


def _report(console, value):
    run_id = value.get("run_id", "—")
    console.print(f"运行 {run_id} · {_status(value.get('status'))}", markup=False, highlight=False)
    valid, expected = value.get("valid_attempts", 0), value.get("expected_attempts", 0)
    complete = "完整" if value.get("complete") else "尚未取得完整有效评分"
    console.print(
        f"有效评分 {valid}/{expected} · {complete} · "
        f"异常 {value.get('invalid_attempts', 0)} · 缺失 {value.get('missing_attempts', 0)}",
        markup=False,
        highlight=False,
    )
    rows = _table(None, "任务", "有效 / 预期", "原评分器均值")
    for task in value.get("tasks", []):
        rows.add_row(
            Text(str(task["task"])),
            Text(f"{task['valid_attempts']}/{task['expected_attempts']}"),
            Text(_display(task.get("mean_rewards"))),
        )
    console.print(rows)
    if value.get("reason"):
        console.print(f"说明：{value['reason']}", markup=False, highlight=False)
    for key in ("raw_results", "worker_log", "manifest"):
        if value.get(key):
            console.print(f"{key}：{value[key]}", markup=False, highlight=False)


def _compare(console, value):
    console.print(f"比较 {value.get('left')} → {value.get('right')}", markup=False, highlight=False)
    if not value.get("comparable"):
        console.print("不可比较，未生成聚合改进结论。", style="yellow")
        for reason in value.get("reasons", []):
            console.print(f"• {reason}", markup=False, highlight=False)
        return
    rows = _table(None, "任务", "基线", "候选", "差值（候选 − 基线）")
    for task in value.get("tasks", []):
        rows.add_row(*(Text(_display(task.get(key))) for key in ("task", "left", "right", "delta")))
    console.print(rows)
    console.print(
        f"平均任务差值：{_display(value.get('mean_task_delta'))}", markup=False, highlight=False
    )
    if value.get("bundle_change"):
        console.print(f"bundle：{_display(value['bundle_change'])}", markup=False, highlight=False)


def render(command, value, *, json_output=False):
    """Print a public result without changing validity, scoring, or exit codes."""
    if json_output:
        print(json.dumps(value, indent=2, ensure_ascii=False))
        return
    if isinstance(value, str):
        print(value)
        return
    console = Console(highlight=False)
    if command == "list" and isinstance(value, list):
        _runs(console, value)
    elif command == "report":
        _report(console, value)
    elif command == "compare":
        _compare(console, value)
    elif command == "doctor":
        rows = _table("环境检查", "检查项", "结果", "说明 / 修复")
        for check in value.get("checks", []):
            state = "通过" if check["ok"] else "失败" if check.get("required", True) else "可选"
            detail = (
                check.get("detail", check.get("actual", ""))
                if check["ok"]
                else check.get("fix", check.get("detail", ""))
            )
            rows.add_row(Text(str(check["check"])), Text(state), Text(_display(detail)))
        console.print(rows)
        console.print("未发送模型请求；环境检查不验证模型认证。", markup=False)
    else:
        _fields(console, value, title=command, omit=("status_command", "pid", "birth", "cancel"))
        if command in {"submit", "rerun"} and value.get("run_id"):
            _hint(console, "status", value["run_id"])
            _hint(console, "logs", value["run_id"])
        elif command == "status":
            _hint(console, "report", value.get("id", value.get("run_id", "<run-id>")))
        elif command.startswith("auth"):
            console.print("仅为本地登录状态，不代表服务认证已验证。", markup=False)
        elif command == "cancel":
            console.print("取消请求已记录；终态 cancelled 才确认停止与清理。", markup=False)
