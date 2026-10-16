import { post } from "@/api";
import { Title } from "@/components/shared";
import { AdminForm } from "@/features/admin/AdminForm";
export function AccountPage({ logout }: { logout: () => void }) {
  return (
    <>
      <Title title="账户与密码" description="管理当前受邀账户的登录密码。" />
      <div className="account-form">
        <AdminForm
          title="修改密码"
          description="成功后所有现有会话失效，请使用新密码重新登录。"
          fields={[
            { name: "current_password", label: "当前密码", type: "password" },
            { name: "password", label: "新密码（至少12位）", type: "password" },
          ]}
          onSave={async (v) => {
            await post("/auth/password", v);
            logout();
          }}
        />
      </div>
    </>
  );
}
