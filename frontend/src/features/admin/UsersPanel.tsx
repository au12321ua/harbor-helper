import { Help } from "@/components/shared";
import { type User } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { AdminForm } from "@/features/admin/AdminForm";
import { useState } from "react";
import type { AdminPanelProps } from "./types";

export function UsersPanel({
  users,
  save,
  action,
}: Omit<AdminPanelProps, "c"> & { users: User[] }) {
  const [reset, setReset] = useState<User>();
  return (
    <TabsContent value="users">
      <div className="admin-layout">
        <div className="flex flex-col gap-4">
          {users.map((u) => (
            <Card key={u.id}>
              <CardHeader>
                <CardTitle>{u.username}</CardTitle>
                <CardDescription>
                  {u.role === "admin" ? (
                    <>
                      管理员{" "}
                      <Help label="管理员角色">
                        管理员默认拥有完整资料权限。
                      </Help>
                    </>
                  ) : (
                    "成员"
                  )}{" "}
                  · {u.enabled ? "启用" : "停用"}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={() =>
                    void action(
                      `/admin/users/${u.id}`,
                      { enabled: !u.enabled },
                      "PATCH",
                    )
                  }
                >
                  {u.enabled ? "停用" : "启用"}
                </Button>
                {u.role !== "admin" ? (
                  <Button
                    variant="outline"
                    onClick={() => {
                      if (
                        u.evidence_grant &&
                        !window.confirm(
                          "撤销将同时吊销该账户所有含 evidence 的自动化凭证；再次授信不会恢复旧凭证。继续？",
                        )
                      )
                        return;
                      void action(
                        `/admin/users/${u.id}/evidence-grant`,
                        { enabled: !u.evidence_grant },
                        "POST",
                      );
                    }}
                  >
                    {u.evidence_grant ? "撤销完整资料授信" : "授予完整资料权限"}
                  </Button>
                ) : null}
                <Button variant="outline" onClick={() => setReset(u)}>
                  重置密码
                </Button>
              </CardContent>
            </Card>
          ))}
          {reset ? (
            <AdminForm
              key={reset.id}
              title={`重置 ${reset.username} 密码`}
              description="将撤销该用户现有会话；请安全交付新密码。"
              fields={[
                {
                  name: "password",
                  label: "新密码（至少12位）",
                  type: "password",
                },
              ]}
              onSave={async (v) => {
                await save(`/admin/users/${reset.id}`, v, "PATCH");
                setReset(undefined);
              }}
            />
          ) : null}
        </div>
        <AdminForm
          title="创建受邀账户"
          description="无公开注册。请安全交付网址和初始密码；成员可以在账户页修改密码。"
          fields={[
            { name: "username", label: "用户名" },
            {
              name: "password",
              label: "初始密码（至少12位）",
              type: "password",
            },
            {
              name: "role",
              label: "角色",
              defaultValue: "member",
              options: [
                { value: "member", label: "成员" },
                { value: "admin", label: "管理员" },
              ],
            },
          ]}
          onSave={(v) => save("/admin/users", v)}
        />
      </div>
    </TabsContent>
  );
}
