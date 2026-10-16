import type { RunDetail } from "@/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { date } from "@/presentation";
export function OverviewPanel({
  row,
  manifest,
  children,
  frozen,
}: Pick<RunDetail, "row" | "manifest"> & {
  children: React.ReactNode;
  frozen: React.ReactNode;
}) {
  return (
    <TabsContent value="overview">
      <div className="detail-overview">
        <div className="flex flex-col gap-4">{children}</div>
        <aside>
          <Card>
            <CardHeader>
              <CardTitle>本次实验快照</CardTitle>
              <CardDescription>
                这些记录属于当前实验，后续配置变更不会改写历史输入。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="detail-grid">
                {Object.entries({
                  数据集:
                    row.dataset || manifest.source?.dataset || manifest.source,
                  模型方案: row.model_profile,
                  开始时间: date(row.started),
                  完成时间: date(row.finished),
                  执行并发: row.concurrency,
                  状态原因: row.reason || "—",
                  作者预构建镜像缓存观察:
                    manifest.service?.author_input_diagnostics?.images
                      ?.map(
                        (image) =>
                          `${image.role} ${image.reference}：${image.cached === true ? "已缓存，不证明兼容" : image.cached === false ? "未缓存；Harbor需向registry获取；up未完成请检查registry与阶段记录，不能直接断言网络根因" : "未知"}`,
                      )
                      .join("；") || "无声明或尚未观察",
                  作者启动时限与有效等待:
                    manifest.startup_policy?.tasks
                      ?.map(
                        (task) =>
                          `${task.task}：作者 ${task.author_build_timeout_sec} 秒 × ${manifest.startup_policy.multiplier} = 准备等待 ${task.start_wait_timeout_sec} 秒；作者网络 ${task.author_network_mode}`,
                      )
                      .join("；") || "未知",
                  环境启动策略: `作者 build_timeout_sec × ${manifest.effective?.environment_build_timeout_multiplier ?? 1}（冻结）；整体运行上限 ${manifest.effective?.wall_seconds ?? "未知"} 秒`,
                  代理工具策略:
                    manifest.effective?.agent === "opencode"
                      ? manifest.effective?.agent_tool_preparation ===
                        "offline-npm-binary-v1"
                        ? "匹配预装优先；任务外公共工具准备 / Harbor上传离线安装（冻结）"
                        : "旧受理：任务内安装（未暗改）"
                      : "参考解，无模型工具安装",
                }).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>
                      {v == null
                        ? "—"
                        : typeof v === "object"
                          ? JSON.stringify(v)
                          : String(v)}
                    </dd>
                  </div>
                ))}
              </dl>
              <details className="raw-details">
                <summary>查看非敏感配置快照</summary>
                <pre>{JSON.stringify(manifest, null, 2)}</pre>
              </details>
            </CardContent>
          </Card>
          {frozen}
        </aside>
      </div>
    </TabsContent>
  );
}
