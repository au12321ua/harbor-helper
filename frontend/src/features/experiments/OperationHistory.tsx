import { api } from "@/api";
import { ErrorNotice, Loading, Title } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { useLoad } from "@/hooks/useLoad";
import { useState } from "react";
import { Link } from "react-router-dom";

export function OperationHistory() {
  const [offset, setOffset] = useState(0);
  const [mine, setMine] = useState(false);
  const { data, error, loading, reload } = useLoad(
    () =>
      api("/operations", {
        query: { offset: String(offset), mine: String(mine) },
      }),
    `${offset}:${mine}`,
  );
  return (
    <>
      <Title
        title="请求历史"
        description="受理与业务拒绝均保留。拒绝不占执行容量；原键同内容可重新裁决，修改输入须换新键。"
      />
      <label>
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
      <Button onClick={() => void reload()}>刷新</Button>
      <ErrorNotice error={error} />
      {loading && <Loading />}
      {data?.operations.map((op) => (
        <details key={op.id}>
          <summary>
            {op.operation} · {op.status} · {op.id} · 尝试 {op.attempts} 次
          </summary>
          <p>
            键：{op.idem} · 成员：{op.user_id} · 已汇总尝试：
            {op.summarized_attempts}
          </p>
          <pre>
            {JSON.stringify(
              {
                request: op.request,
                result: op.result,
                error: op.error,
                recent: op.recent,
              },
              null,
              2,
            )}
          </pre>
          {typeof op.result?.id === "string" &&
            op.result.id.startsWith("sub-") && (
              <Link to={`/submissions/${op.result.id}`}>查看提交</Link>
            )}
        </details>
      ))}
      <Button
        disabled={!offset}
        onClick={() => setOffset(Math.max(0, offset - 50))}
      >
        上一页
      </Button>
      <Button
        disabled={data?.next_offset == null}
        onClick={() => setOffset(data?.next_offset ?? 0)}
      >
        下一页
      </Button>
    </>
  );
}
