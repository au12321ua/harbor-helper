import { api } from "@/api";
import {
  EmptyState,
  ErrorNotice,
  Help,
  Loading,
  SelectField,
  Title,
} from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useLoad } from "@/hooks/useLoad";
import { date } from "@/presentation";
import { useState } from "react";
import { Link } from "react-router-dom";

const operations: Record<string, string> = {
  submit: "提交实验",
  rerun: "重跑实验",
  retry: "重试提交",
  recover: "恢复清理",
  cancel: "取消任务",
  attachment_create: "新建附件",
  attachment_publish: "发布附件版本",
  attachment_derive: "派生附件",
};
const preparation: Record<string, string> = {
  preparing: "准备中",
  ready: "已生成实验",
  cancelled: "已取消",
  failed: "准备失败",
};
function reason(error: Record<string, unknown> | null | undefined) {
  if (!error) return "";
  const messages: Record<string, string> = {
    idempotency_conflict: "同一个请求键使用了不同输入，请开始新操作",
    queue_full: "队列已满，请稍后重试",
    maintenance: "服务维护中，暂停受理",
    admission_paused: "服务暂停受理",
    run_missing: "关联实验不存在或已删除",
  };
  return (
    messages[String(error.code)] ||
    `原因：${String(error.message || error.code || "未知原因")}`
  );
}
export function OperationHistory() {
  const [offset, setOffset] = useState(0),
    [mine, setMine] = useState(false),
    [operation, setOperation] = useState(""),
    [status, setStatus] = useState("");
  const {
    data,
    error,
    loading: initialLoading,
    refreshing,
    reload,
  } = useLoad(
    () =>
      api("/operations", {
        query: {
          offset: String(offset),
          mine: String(mine),
          ...(operation ? { operation } : {}),
          ...(status ? { status } : {}),
        },
      }),
    `${offset}:${mine}:${operation}:${status}`,
  );
  const loading = initialLoading || refreshing;
  return (
    <>
      <Title
        title="请求历史"
        description="查看团队请求的受理记录与提交准备进度。"
      />
      <div className="history-toolbar">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={mine}
            onChange={(e) => {
              setMine(e.target.checked);
              setOffset(0);
            }}
          />
          仅本人
        </label>
        <SelectField
          label="操作"
          name="history-operation"
          required={false}
          value={operation}
          onChange={(v) => {
            setOperation(v);
            setOffset(0);
          }}
        >
          <option value="">全部操作</option>
          {Object.entries(operations).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="受理结果"
          name="history-status"
          required={false}
          value={status}
          onChange={(v) => {
            setStatus(v);
            setOffset(0);
          }}
        >
          <option value="">全部结果</option>
          <option value="accepted">已受理</option>
          <option value="rejected">已拒绝</option>
        </SelectField>
        <Button
          variant="outline"
          disabled={loading}
          onClick={() => void reload()}
        >
          刷新
        </Button>
        <Help label="请求重试规则">
          受理不等于实验成功。拒绝不占执行容量；原键同内容可重新裁决，修改输入须换新键。最近重试被拒不会改变原来的受理结果。
        </Help>
      </div>
      <ErrorNotice error={error} />
      {loading ? (
        <Loading />
      ) : !error && data?.operations.length === 0 ? (
        <EmptyState
          title="暂无请求记录"
          description="当前筛选范围没有记录，可调整筛选或提交实验后刷新。"
        />
      ) : null}
      {!loading &&
        data?.operations.map((op) => {
          const result = op.result,
            submission =
              typeof result?.id === "string" && result.id.startsWith("sub-")
                ? result.id
                : undefined;
          const recentError = op.recent.at(-1)?.error as
            Record<string, unknown> | undefined;
          return (
            <article className="history-record" key={op.id}>
              <div className="section-bar">
                <strong>{operations[op.operation] || op.operation}</strong>
                <Badge variant="secondary">
                  {op.status === "accepted" ? "已受理" : "已拒绝"}
                </Badge>
              </div>
              <p>
                {op.username || `用户 ${op.user_id.slice(0, 8)}`} ·{" "}
                {date(op.created)} · 请求 {op.attempts} 次
              </p>
              {op.error && <p role="status">{reason(op.error)}</p>}
              {submission && (
                <p>
                  提交准备：
                  {preparation[String(result?.status)] ||
                    "状态未知或记录已删除"}
                  {result?.error
                    ? ` · ${reason(typeof result.error === "object" ? (result.error as Record<string, unknown>) : { message: result.error })}`
                    : ""}
                </p>
              )}
              {recentError && (
                <p className="text-destructive">
                  最近一次重试被拒：{reason(recentError)}
                </p>
              )}
              <div className="flex flex-wrap gap-3">
                {submission && (
                  <Link to={`/submissions/${submission}`}>查看提交</Link>
                )}
                {typeof result?.run_id === "string" && (
                  <Link to={`/runs/${result.run_id}`}>查看实验</Link>
                )}
              </div>
              <details className="raw-details">
                <summary>请求详情 · {op.id.slice(0, 11)}</summary>
                <p>
                  请求编号：{op.id}{" "}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void navigator.clipboard.writeText(op.id)}
                  >
                    复制编号
                  </Button>
                </p>
                <p>
                  幂等键：{op.idem} · 更新时间：{date(op.updated)} ·
                  已汇总尝试：{op.summarized_attempts}
                </p>
                <pre>
                  {JSON.stringify(
                    {
                      request: op.request,
                      result,
                      error: op.error,
                      recent: op.recent,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </article>
          );
        })}
      <div className="history-pagination">
        <span>
          {data?.total
            ? `${offset + 1}–${Math.min(offset + (data.operations.length || 0), data.total)} / ${data.total} 条`
            : "0 条记录"}
        </span>
        <Button
          variant="outline"
          disabled={loading || !offset}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          上一页
        </Button>
        <Button
          variant="outline"
          disabled={loading || data?.next_offset == null}
          onClick={() => setOffset(data?.next_offset ?? 0)}
        >
          下一页
        </Button>
      </div>
    </>
  );
}
