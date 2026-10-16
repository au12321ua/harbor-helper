import { ErrorNotice } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { date } from "@/presentation";
import type { useDockerDiagnostics } from "./useDockerDiagnostics";

export function RuntimePanel({
  diagnostics,
}: {
  diagnostics: ReturnType<typeof useDockerDiagnostics>;
}) {
  const { docker, dockerBusy, dockerError, discoverDocker } = diagnostics;
  return (
    <TabsContent value="runtime">
      <Card>
        <CardHeader>
          <CardTitle>服务端 Docker 与镜像库存</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p>只读诊断，不拉取、构建或删除镜像。库存不代表 benchmark 兼容性。</p>
          <Button disabled={dockerBusy} onClick={() => void discoverDocker()}>
            {dockerBusy ? "发现中…" : "发现本机 Docker 与镜像"}
          </Button>
          <ErrorNotice error={dockerError} />
          {docker ? (
            <>
              <p role="status">{docker.message}</p>
              <p>发现时间：{date(docker.checked_at)}</p>
              {(docker.images || []).map((image) => (
                <p key={image.reference}>{image.reference}</p>
              ))}
            </>
          ) : null}
        </CardContent>
      </Card>
    </TabsContent>
  );
}
