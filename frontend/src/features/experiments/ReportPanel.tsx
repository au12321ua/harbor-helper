import type { RunDetail } from "@/api";
import { EmptyState } from "@/components/shared";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { Download } from "lucide-react";
import { Rewards } from "./Rewards";
export function ReportPanel({ data }: { data: RunDetail }) {
  const { row } = data;
  const id = row.id;
  return (
    <TabsContent value="report">
      {data?.report ? (
        <Card>
          <CardHeader>
            <CardTitle>评分报告</CardTitle>
            <Button
              variant="outline"
              onClick={() => {
                window.location.href = `/api/v1/runs/${id}/report/download`;
              }}
            >
              <Download data-icon="inline-start" />
              下载评分报告
            </Button>
            <CardDescription>
              保留合法零分，单独记录缺失和无效尝试。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Rewards report={data.report} />
          </CardContent>
        </Card>
      ) : (
        <EmptyState
          title="报告暂不可用"
          description={
            row.audit_status === "incomplete"
              ? "审计异常限制了报告展示。"
              : "等待任务运行、资源收尾与报告发布。"
          }
        />
      )}
    </TabsContent>
  );
}
