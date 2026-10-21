import { api, newIdempotencyKey, post, type User } from "@/api";
import { ErrorNotice, Loading, Status, Title } from "@/components/shared";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useLoad } from "@/hooks/useLoad";
import { fromParent, fromRequest } from "./reuse";
import { terminal } from "@/presentation";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
export function Submission({ user }: { user: User }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const recoveryKey = useRef(newIdempotencyKey());
  const copyRequest = useRef(0);
  useEffect(() => {
    return () => {
      copyRequest.current++;
    };
  }, [id]);
  const [recovering, setRecovering] = useState(false);
  const { data, error, loading, reload } = useLoad(
    () => api(`/submissions/${id}`),
    id || "",
    2000,
  );
  useEffect(() => {
    if (data?.run_id) navigate(`/runs/${data.run_id}`, { replace: true });
  }, [data?.run_id, navigate]);
  if (loading) return <Loading />;
  return (
    <>
      <Title
        title={
          (data?.request_group ? String(data.request_group.name || "未命名 · " + String(data.request_group.group_id).slice(4, 12)) : data?.request?.name) ||
          (data?.status === "failed"
            ? "实验准备失败"
            : data?.status === "cancelled"
              ? "实验已取消"
              : "实验准备")
        }
        description={`提交 ${id}`}
      />
      <ErrorNotice error={error} />
      <Card>
        <CardHeader>
          <CardTitle>
            <Status value={data?.status || ""} preparation />
          </CardTitle>
          <CardDescription>
            {data?.status === "failed"
              ? "本次准备已停止。修复配置或修改输入后重新提交，会创建新的实验。"
              : data?.status === "cancelled"
                ? "本次提交已取消。"
                : "数据源解析与准备完成后，自动进入统一队列。"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p>提交时名称：{data?.request?.name || "（空）"}</p>
          <p>提交者：{data?.submitter || "—"}</p>
          {data?.error ? (
            <Alert variant="destructive">
              <AlertDescription>
                {typeof data.error === "string"
                  ? data.error
                  : JSON.stringify(data.error)}
              </AlertDescription>
            </Alert>
          ) : null}
          {data &&
          !terminal(data.status) &&
          (user.role === "admin" || data.submitter === user.username) ? (
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  await post(`/submissions/${id}/cancel`);
                  await reload();
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              取消提交
            </Button>
          ) : null}
          {data?.status === "failed" ? (
            <>
              <Button
                disabled={recovering}
                onClick={async () => {
                  setRecovering(true);
                  try {
                    const result = await post(
                      `/submissions/${id}/retry`,
                      {},
                      recoveryKey.current,
                    );
                    navigate(`/submissions/${result.id}`);
                  } catch (error) {
                    toast.error((error as Error).message);
                  } finally {
                    setRecovering(false);
                  }
                }}
              >
                按当前配置再次提交（保留原来源）
              </Button>
              {data.diagnosis?.map((issue, index: number) => (
                <p key={index}>
                  {issue.task}：{(issue.variables || []).join("、")} ·{" "}
                  {issue.reason}
                </p>
              ))}
              {user.role === "admin" ? (
                <Button variant="outline" asChild>
                  <Link to="/admin">修复团队配置</Link>
                </Button>
              ) : (
                <p>数据源权限或运行镜像问题请联系管理员在网页修复。</p>
              )}
            </>
          ) : null}
          {data && !data.run_id && (
            <Button
              variant="outline"
              disabled={recovering}
              onClick={async () => {
                setRecovering(true);
                const token = ++copyRequest.current;
                try {
                  const entry = data.parent
                    ? fromParent(
                        (await api(`/runs/${data.parent}`)).manifest,
                        data.request,
                        `提交 ${data.id}`,
                      )
                    : fromRequest(data.request, `提交 ${data.id}`);
                  entry.sourceId = data.id;
                  if (token === copyRequest.current)
                    navigate("/new", { state: { entry } });
                } catch (error) {
                  toast.error(
                    `恢复失败，未打开副本：${(error as Error).message}`,
                  );
                } finally {
                  setRecovering(false);
                }
              }}
            >
              {data.status === "failed" ? "修改输入后新提交" : "复制配置新建"}
            </Button>
          )}
          <Button variant="ghost" asChild>
            <Link to="/">返回实验列表</Link>
          </Button>
        </CardContent>
      </Card>
    </>
  );
}
