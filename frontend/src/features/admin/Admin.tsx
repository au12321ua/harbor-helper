import { api } from "@/api";
import { ErrorNotice, Loading, Title } from "@/components/shared";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLoad } from "@/hooks/useLoad";
import { useSearchParams } from "react-router-dom";
import { DatasetsPanel } from "./DatasetsPanel";
import { LimitsPanel } from "./LimitsPanel";
import { ModelsPanel } from "./ModelsPanel";
import { RuntimePanel } from "./RuntimePanel";
import { SecurityPanel } from "./SecurityPanel";
import { SourcesPanel } from "./SourcesPanel";
import { useAdminActions } from "./useAdminActions";
import { useDockerDiagnostics } from "./useDockerDiagnostics";
import { UsersPanel } from "./UsersPanel";
export function Admin() {
  const { data, error, loading, reload } = useLoad(() =>
    Promise.all([api("/admin/users"), api("/catalog")]),
  );
  const [params, setParams] = useSearchParams();
  const requested = params.get("section") || "readiness";
  const tab = [
    "readiness",
    "runtime",
    "dataset",
    "models",
    "users",
    "limits",
    "security",
  ].includes(requested)
    ? requested
    : "readiness";
  const setTab = (value: string) =>
    setParams({ section: value }, { replace: true });
  const { saving, save, action } = useAdminActions(reload);
  const diagnostics = useDockerDiagnostics();
  if (loading) return <Loading />;
  if (!data) return <ErrorNotice error={error} />;
  const [users, c] = data;
  return (
    <>
      <Title
        title="团队管理"
        description="验证 benchmark 来源，再配置模型和受邀成员。环境按作者定义执行。"
      />
      <ErrorNotice error={error} />
      {saving ? (
        <p role="status">正在保存并刷新配置，完成后可继续编辑。</p>
      ) : null}
      <fieldset disabled={saving} aria-busy={saving} className="min-w-0">
        <Tabs className="admin-workspace" value={tab} onValueChange={setTab}>
          <TabsList className="admin-tabs">
            <TabsTrigger value="readiness">就绪与来源</TabsTrigger>
            <TabsTrigger value="runtime">Docker 诊断</TabsTrigger>
            <TabsTrigger value="dataset">数据集</TabsTrigger>
            <TabsTrigger value="models">模型与 key</TabsTrigger>
            <TabsTrigger value="users">受邀账户</TabsTrigger>
            <TabsTrigger value="security">安全与主密钥</TabsTrigger>
            <TabsTrigger value="limits">容量与保留</TabsTrigger>
          </TabsList>
          <SecurityPanel />
          <SourcesPanel c={c} save={save} />
          <RuntimePanel diagnostics={diagnostics} />
          <DatasetsPanel
            c={c}
            save={save}
            action={action}
            diagnostics={diagnostics}
          />
          <ModelsPanel c={c} save={save} action={action} />
          <UsersPanel users={users} save={save} action={action} />
          <LimitsPanel c={c} save={save} reload={reload} />
        </Tabs>
      </fieldset>
    </>
  );
}
