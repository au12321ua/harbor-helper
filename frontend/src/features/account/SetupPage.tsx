import { ThemeToggle } from "@/components/ThemeToggle";
import { HarborMark } from "@/components/HarborMark";
import { post } from "@/api";
import { AdminForm } from "@/features/admin/AdminForm";
export function SetupPage({ done }: { done: () => void }) {
  return (
    <div className="login-page">
      <ThemeToggle />
      <div className="login-brand">
        <HarborMark />
        <span>Harbor Helper</span>
      </div>
      <AdminForm
        title="首次网站设置"
        description="需要部署负责人交付的一次性引导凭证；本网站不开放注册。主密钥在数据库外生成，不会回显。"
        fields={[
          { name: "setup_token", label: "部署引导凭证", type: "password" },
          { name: "team_name", label: "团队名称", defaultValue: "团队实验室" },
          { name: "username", label: "首管理员用户名" },
          {
            name: "password",
            label: "管理员密码（至少12位）",
            type: "password",
          },
        ]}
        onSave={async (v) => {
          await post("/setup", v);
          done();
        }}
      />
    </div>
  );
}
