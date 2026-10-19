import { api } from "@/api";
import {
  EmptyState,
  ErrorNotice,
  Loading,
  Status,
  Title,
} from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ReadinessSummary } from "@/features/admission/ReadinessPanel";
import { useLoad } from "@/hooks/useLoad";
import { canCompare, date, terminal } from "@/presentation";
import { GitCompareArrows, Plus, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
const active = new Set([
  "starting",
  "running",
  "cancelling",
  "cleanup_blocked",
]);
const filters = [
  ["all", "全部"],
  ["active", "活动"],
  ["queued", "排队"],
  ["terminal", "终态"],
] as const;
export function ExperimentList() {
  const { data, error, loading, reload, updatedAt } = useLoad(
    () =>
      Promise.all([
        api("/runs"),
        api("/usage"),
        api("/catalog"),
        api("/readiness"),
      ]),
    "",
    4000,
  );
  const [params, setParams] = useSearchParams();
  const pendingParams = useRef(params);
  useEffect(() => {
    pendingParams.current = params;
  }, [params]);
  const filter = params.get("q") || "";
  const state = filters.some(([v]) => v === params.get("status"))
    ? params.get("status")!
    : "all";
  const [selected, setSelected] = useState<string[]>([]);
  const [selectionMessage, setSelectionMessage] = useState("");
  const [allSubmissions, setAllSubmissions] = useState(false);
  function update(name: string, value: string) {
    const next = new URLSearchParams(pendingParams.current);
    if (value && value !== "all") next.set(name, value);
    else next.delete(name);
    pendingParams.current = next;
    setParams(next, { replace: true });
  }
  if (loading) return <Loading />;
  if (!data)
    return (
      <>
        <Title title="共享实验" description="实验记录暂未加载。" />
        <ErrorNotice error={error} />
        <Button
          variant="outline"
          className="self-start"
          onClick={() => void reload()}
        >
          重试加载
        </Button>
      </>
    );
  const [{ runs, submissions }, usage, catalog, readiness] = data;
  const eligibleSelected = selected.filter((id) =>
    runs.some((r) => r.id === id && canCompare(r)),
  );
  const counts = {
    all: runs.length,
    active: runs.filter((r) => active.has(r.status)).length,
    queued: runs.filter((r) => r.status === "queued").length,
    terminal: runs.filter((r) => terminal(r.status)).length,
  };
  const shown = runs.filter(
    (r) =>
      (state === "all" ||
        (state === "active"
          ? active.has(r.status)
          : state === "queued"
            ? r.status === "queued"
            : terminal(r.status))) &&
      [r.id, r.name, r.submitter, r.dataset, r.model_profile, r.agent]
        .join(" ")
        .toLowerCase()
        .includes(filter.toLowerCase()),
  );
  const preparing = submissions.filter((s) => !s.run_id);
  const visibleSubmissions = allSubmissions
    ? preparing
    : preparing
        .filter((s) => !terminal(s.status))
        .concat(preparing.filter((s) => terminal(s.status)).slice(0, 3));
  const listUrl = "/" + (params.size ? `?${params}` : "");
  return (
    <>
      <Title
        title="共享实验"
        description=""
        action={
          <Button asChild>
            <Link to="/new">
              <Plus />
              新建实验
            </Link>
          </Button>
        }
      />
      <ErrorNotice error={error} />
      <ReadinessSummary
        value={readiness}
        stale={!!error}
        usage={usage}
        limits={catalog.limits}
      />
      {error && (
        <p className="freshness" role="status">
          上次成功更新 {updatedAt ? date(updatedAt / 1000) : "未知"} ·
          刷新失败，当前为旧数据
        </p>
      )}
      <div className="list-toolbar">
        <div className="filter-tabs" aria-label="实验状态筛选">
          {filters.map(([key, label]) => (
            <button
              key={key}
              aria-label={`${label} ${counts[key]}`}
              aria-pressed={state === key}
              onClick={() => update("status", key)}
            >
              {label}
              <small>{counts[key]}</small>
            </button>
          ))}
        </div>
        <div className="search-controls">
          <Input
            aria-label="搜索实验"
            placeholder="搜索实验、ID、数据集…"
            value={filter}
            onChange={(e) => update("q", e.target.value)}
          />
          <Button
            variant="outline"
            size="icon"
            aria-label="刷新实验"
            onClick={() => void reload()}
          >
            <RefreshCw />
          </Button>
          <Button
            variant="outline"
            disabled={eligibleSelected.length !== 2}
            asChild={eligibleSelected.length === 2}
          >
            {eligibleSelected.length === 2 ? (
              <Link
                to={`/compare?left=${encodeURIComponent(eligibleSelected[0])}&right=${encodeURIComponent(eligibleSelected[1])}`}
              >
                <GitCompareArrows />
                对比实验
              </Link>
            ) : (
              <>
                <GitCompareArrows />
                对比实验
              </>
            )}
          </Button>
        </div>
      </div>
      {(selected.length > 0 || selectionMessage) && (
        <div className="selection-bar" role="status">
          {eligibleSelected.map((id, i) => (
            <span key={id}>
              实验 {i === 0 ? "A" : "B"}：
              {runs.find((r) => r.id === id)?.name || id}
            </span>
          ))}
          {selectionMessage}
          <Button
            variant="ghost"
            onClick={() => {
              setSelected([]);
              setSelectionMessage("");
            }}
          >
            清空选择
          </Button>
        </div>
      )}
      <div className={`table-shell ${error ? "stale" : ""}`}>
        <Table className="run-table">
          <TableHeader>
            <TableRow>
              <TableHead aria-label="对比选择" />
              <TableHead>实验 / ID</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>数据集</TableHead>
              <TableHead>执行配置</TableHead>
              <TableHead>提交者</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead>审计</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => {
              const index = eligibleSelected.indexOf(r.id),
                eligible = canCompare(r);
              return (
                <TableRow
                  key={r.id}
                  data-state={index >= 0 ? "selected" : undefined}
                >
                  <TableCell
                    title={
                      eligible
                        ? "选择两次实验进行对比"
                        : "报告未发布：运行未结束或审计未完成"
                    }
                  >
                    <input
                      type="checkbox"
                      aria-label={`选择实验 ${r.name || r.id}`}
                      aria-describedby={
                        !eligible ? `eligibility-${r.id}` : undefined
                      }
                      disabled={!eligible}
                      checked={index >= 0}
                      onChange={() => {
                        if (index >= 0) {
                          setSelected(
                            eligibleSelected.filter((id) => id !== r.id),
                          );
                          setSelectionMessage("");
                        } else if (eligibleSelected.length < 2) {
                          setSelected([...eligibleSelected, r.id]);
                          setSelectionMessage("");
                        } else
                          setSelectionMessage(
                            "已选择 A/B 两次实验，请先取消一项或清空选择。",
                          );
                      }}
                    />
                    {!eligible && (
                      <span id={`eligibility-${r.id}`} className="sr-only">
                        报告未发布：运行未结束或审计未完成
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="name-cell">
                    <Link
                      className="run-link"
                      to={`/runs/${r.id}`}
                      state={{ listUrl }}
                    >
                      {r.name || r.id}
                    </Link>
                    <div className="cell-secondary" title={r.id}>
                      {index >= 0 && (
                        <span className="text-primary">
                          {index === 0 ? "A · " : "B · "}
                        </span>
                      )}
                      {r.id.slice(0, 12)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Status value={r.status} />
                  </TableCell>
                  <TableCell className="mono">{r.dataset || "—"}</TableCell>
                  <TableCell className="mono">
                    {[r.agent, r.model_profile].filter(Boolean).join(" · ") ||
                      "—"}
                  </TableCell>
                  <TableCell>{r.submitter || "—"}</TableCell>
                  <TableCell
                    className="mono whitespace-nowrap"
                    title={date(r.created)}
                  >
                    {shortDate(r.created)}
                  </TableCell>
                  <TableCell>
                    <Status value={r.audit_status} />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {!shown.length && (
          <EmptyState
            title={runs.length ? "没有匹配的实验" : undefined}
            description={
              runs.length ? "调整状态筛选或搜索条件后重试。" : undefined
            }
          />
        )}
        <div className="table-footnote">
          显示 {shown.length} / {runs.length} 条实验 · 状态定期刷新
        </div>
      </div>
      {preparing.length > 0 && (
        <section className="submission-section">
          <div className="section-bar">
            <h2>
              受理准备<span>{preparing.length}</span>
            </h2>
            <span className="quiet-note">来源解析完成后生成实验记录</span>
          </div>
          <div className="table-shell">
            <Table className="submission-table">
              <TableHeader>
                <TableRow>
                  <TableHead>提交 / ID</TableHead>
                  <TableHead>准备状态</TableHead>
                  <TableHead>提交者</TableHead>
                  <TableHead>时间</TableHead>
                  <TableHead>安全摘要</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleSubmissions.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>
                      <Link className="run-link" to={`/submissions/${s.id}`}>
                        {s.request?.name || s.id}
                      </Link>
                      <div className="cell-secondary">{s.id}</div>
                    </TableCell>
                    <TableCell>
                      <Status value={s.status} preparation />
                    </TableCell>
                    <TableCell>{s.submitter}</TableCell>
                    <TableCell className="mono">
                      {shortDate(s.created)}
                    </TableCell>
                    <TableCell>
                      {s.error ||
                        (s.status === "cancelled"
                          ? "准备已取消"
                          : s.status === "ready"
                            ? "准备完成"
                            : "等待数据源解析与入队")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {preparing.length > visibleSubmissions.length && (
              <Button variant="ghost" onClick={() => setAllSubmissions(true)}>
                显示全部提交（{preparing.length}）
              </Button>
            )}
          </div>
        </section>
      )}
      <p className="quiet-note">
        运行时长和并发限制控制资源使用，不代表准确的费用预算。
      </p>
    </>
  );
}
function shortDate(value: number) {
  return date(value, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
