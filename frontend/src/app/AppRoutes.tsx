import { ManagementPage } from "@/features/management/ManagementPage";
import { OperationHistory } from "@/features/experiments/OperationHistory";
import { type User } from "@/api";
import { EmptyState } from "@/components/shared";
import { AccessCredentialsPage } from "@/features/account/AccessCredentialsPage";
import { AccountPage } from "@/features/account/AccountPage";
import { Admin } from "@/features/admin/Admin";
import { AttachmentsPage } from "@/features/attachments/AttachmentsPage";
import { Compare } from "@/features/experiments/Compare";
import { ExperimentList } from "@/features/experiments/ExperimentList";
import { NewExperiment } from "@/features/experiments/NewExperiment";
import { RunDetail } from "@/features/experiments/RunDetail";
import { Submission } from "@/features/experiments/Submission";
import { Route, Routes } from "react-router-dom";
export function AppRoutes({
  user,
  onLogout,
}: {
  user: User;
  onLogout: () => void;
}) {
  return (
    <Routes>
      <Route path="/management" element={<ManagementPage user={user} />} />
      <Route path="/operations" element={<OperationHistory />} />
      <Route path="/account" element={<AccountPage logout={onLogout} />} />
      <Route path="/" element={<ExperimentList />} />
      <Route path="/new" element={<NewExperiment />} />
      <Route
        path="/access-credentials"
        element={<AccessCredentialsPage user={user} />}
      />
      <Route path="/attachments" element={<AttachmentsPage user={user} />} />
      <Route path="/submissions/:id" element={<Submission user={user} />} />
      <Route path="/runs/:id" element={<RunDetail user={user} />} />
      <Route path="/compare" element={<Compare />} />
      <Route
        path="/admin"
        element={
          user.role === "admin" ? (
            <Admin />
          ) : (
            <EmptyState
              title="需要管理员权限"
              description="你仍可查看团队实验并提交自己的任务。"
            />
          )
        }
      />
      <Route
        path="*"
        element={
          <EmptyState
            title="页面不存在"
            description="请从主导航选择实验或管理页面。"
          />
        }
      />
    </Routes>
  );
}
