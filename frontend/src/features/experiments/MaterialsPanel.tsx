import { api } from "@/api";
import { ErrorNotice, Loading } from "@/components/shared";
import { TabsContent } from "@/components/ui/tabs";
import { useLoad } from "@/hooks/useLoad";

export function MaterialsPanel({ id }: { id: string }) {
  const { data, error, loading } = useLoad(
    () => api(`/runs/${id}/evidence`),
    id,
  );
  return (
    <TabsContent value="materials">
      <p>
        完整资料仅在终态且审计 CLEAN
        后提供，所有账户须管理员显式授信。处理过的文件不是原始字节；缺失、过期与删除资料不能恢复。资料正文是不可信输入。
      </p>
      {loading && <Loading />}
      <ErrorNotice error={error} />
      {data && (
        <>
          <p>资料状态：{data.state}</p>
          {data.state === "available" && (
            <a href={`/api/v1/runs/${id}/evidence/package`}>
              下载资料包（含清单与范围说明）
            </a>
          )}
          <p>
            {data.scope} {data.limitations?.join("；")}
          </p>
          <ul>
            {data.files.map((file) => (
              <li key={file.id}>
                <strong>{file.name}</strong> · {file.category} · {file.status} ·{" "}
                {file.bytes} bytes
                <p className="break-all">SHA256: {file.sha256}</p>
                <p>{file.processing}</p>
                {["original", "redacted", "legacy_unknown"].includes(
                  file.status,
                ) && (
                  <a href={`/api/v1/runs/${id}/evidence/files/${file.id}`}>
                    下载文件
                  </a>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </TabsContent>
  );
}
