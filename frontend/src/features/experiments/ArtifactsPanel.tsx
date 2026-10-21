import type { RunDetail } from "@/api";
import { api, type User } from "@/api";
import { EmptyState } from "@/components/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TabsContent } from "@/components/ui/tabs";
import { terminal } from "@/presentation";
import { Download, Trash2 } from "lucide-react";
import { toast } from "sonner";
export function ArtifactsPanel({
  data,
  user,
  reload,
}: {
  data: RunDetail;
  user: User;
  reload: () => Promise<void>;
}) {
  const { row } = data;
  const id = row.id;
  return (
    <TabsContent value="artifacts">
      <div className="table-shell">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>产物名称</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.artifacts || []).map((a) => (
              <TableRow key={a.id}>
                <TableCell>
                  {a.name}
                  {a.deleted ? <Badge variant="secondary">已删除</Badge> : null}
                </TableCell>
                <TableCell>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={a.deleted || row.audit_status === "incomplete"}
                      onClick={() => {
                        window.location.href = `/api/v1/runs/${id}/artifacts/${encodeURIComponent(a.id)}`;
                      }}
                    >
                      <Download data-icon="inline-start" />
                      下载
                    </Button>
                    {user.role === "admin" &&
                    terminal(row.status) &&
                    !a.deleted ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={async () => {
                          if (
                            !window.confirm(
                              `将产物 ${a.name} 移入回收站？可以恢复；原有保留期仍继续计算。`,
                            )
                          )
                            return;
                          try {
                            await api(
                              `/runs/${id}/artifacts/${encodeURIComponent(a.id)}`,
                              { method: "DELETE" },
                            );
                            await reload();
                            toast.success("产物已移入回收站，可到请求与目录管理恢复");
                          } catch (e) {
                            toast.error((e as Error).message);
                          }
                        }}
                      >
                        <Trash2 data-icon="inline-start" />
                        移入回收站
                      </Button>
                    ) : null}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!data?.artifacts?.length ? (
          <EmptyState
            title="暂无可展示产物"
            description="产物在运行与安全审计完成后展示。"
          />
        ) : null}
      </div>
    </TabsContent>
  );
}
