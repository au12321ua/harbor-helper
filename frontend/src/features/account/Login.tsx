import { post, type User } from "@/api";
import { ErrorNotice } from "@/components/shared";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { FlaskConical, LoaderCircle } from "lucide-react";
import { useState } from "react";
export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  return (
    <div className="login-page">
      <div className="login-brand">
        <FlaskConical />
        <span>Harbor Helper</span>
      </div>
      <Card className="login-card">
        <CardHeader>
          <CardTitle>
            <h1>登录团队实验室</h1>
          </CardTitle>
          <CardDescription>使用管理员为你创建的受邀账户。</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError(undefined);
              const f = new FormData(e.currentTarget);
              try {
                const value = await post("/auth/login", {
                  username: String(f.get("username") || ""),
                  password: String(f.get("password") || ""),
                });
                onLogin(value.user);
              } catch (err) {
                setError(err);
              } finally {
                setBusy(false);
              }
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="username">账户</FieldLabel>
                <Input
                  id="username"
                  name="username"
                  autoComplete="username"
                  required
                  autoFocus
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="password">密码</FieldLabel>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </Field>
              <ErrorNotice error={error} />
              <Button disabled={busy} type="submit">
                {busy ? (
                  <LoaderCircle
                    data-icon="inline-start"
                    className="animate-spin"
                  />
                ) : null}
                登录
              </Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
      <p className="login-footer">团队共享实验 · 无开放注册</p>
    </div>
  );
}
