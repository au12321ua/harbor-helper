import {
  api,
  post,
  type AccessCredential,
  type AccessIssue,
  type User,
} from "@/api";
import { ErrorNotice, Help, Loading, Title } from "@/components/shared";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { useLoad } from "@/hooks/useLoad";
import { date } from "@/presentation";
import { useState } from "react";

const scopes = [
  ["read", "发现与读取共享实验"],
  ["attachments", "上传和维护有权维护的附件"],
  ["execute", "提交、重跑、修复与恢复实验"],
  ["cancel_own", "取消自己的任务"],
  ["evidence", "完整实验资料（须同时选择读取）"],
];
export function AccessCredentialsPage({ user }: { user: User }) {
  const { data: capabilities } = useLoad(() => api("/access-capabilities"));
  const [all, setAll] = useState(false);
  const [observedAt] = useState(() => Date.now());
  const { data, error, loading, reload } = useLoad<AccessCredential[]>(
    () => api(all ? "/admin/access-credentials" : "/access-credentials"),
    String(all),
  );
  const [failure, setFailure] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<string>();
  return (
    <>
      <Title
        title="自动化访问凭证"
        description="授权客户端代你操作。默认只读；执行能力须显式选择。"
      />
      <ErrorNotice error={failure || error} />
      {issued && (
        <Card>
          <CardHeader>
            <CardTitle>原值仅显示这一次</CardTitle>
            <CardDescription>
              请保存到安全凭证文件，勿写入附件、命令参数或日志。关闭后无法找回。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Input aria-label="新签发凭证" readOnly value={issued} />
            <Button type="button" onClick={() => setIssued(undefined)}>
              已安全保存，关闭原值
            </Button>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <div className="field-heading">
            <CardTitle>签发凭证</CardTitle>
            <Help label="签发凭证">
              签发须复核当前密码；到期、撤销、账户停用或密码重置后失效。自动化凭证不具有管理员操作权，完整资料需要读取与
              evidence 两项能力。
            </Help>
          </div>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const form = event.currentTarget,
                values = new FormData(form);
              setBusy(true);
              setFailure(undefined);
              setIssued(undefined);
              try {
                const value = await post("/access-credentials", {
                  name: String(values.get("name") || ""),
                  current_password: String(
                    values.get("current_password") || "",
                  ),
                  expires:
                    Date.now() / 1000 + Number(values.get("days")) * 86400,
                  scopes: values
                    .getAll("scopes")
                    .filter(
                      (
                        scope,
                      ): scope is NonNullable<AccessIssue["scopes"]>[number] =>
                        typeof scope === "string" &&
                        [
                          "read",
                          "attachments",
                          "execute",
                          "cancel_own",
                          "evidence",
                        ].includes(scope),
                    ),
                });
                setIssued(value.token);
                form.reset();
                await reload();
              } catch (e) {
                setFailure(e);
              } finally {
                (
                  form.elements.namedItem(
                    "current_password",
                  ) as HTMLInputElement
                ).value = "";
                setBusy(false);
              }
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="access-name">用途名称</FieldLabel>
                <Input id="access-name" name="name" required maxLength={128} />
              </Field>
              <Field>
                <FieldLabel htmlFor="access-days">有效天数</FieldLabel>
                <Input
                  id="access-days"
                  name="days"
                  type="number"
                  required
                  min={1}
                  defaultValue={30}
                />
              </Field>
              <FieldSet>
                <FieldLegend>固定能力</FieldLegend>
                {scopes
                  .filter(([value]) => capabilities?.scopes.includes(value))
                  .map(([value, label]) => (
                    <label key={value} className="flex gap-2 my-2">
                      <input
                        type="checkbox"
                        name="scopes"
                        value={value}
                        defaultChecked={value === "read"}
                      />
                      {label}
                    </label>
                  ))}
              </FieldSet>
              <Field>
                <FieldLabel htmlFor="access-password">当前密码</FieldLabel>
                <Input
                  id="access-password"
                  name="current_password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </Field>
              <Button disabled={busy}>签发凭证</Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
      {user.role === "admin" && (
        <label className="flex gap-2">
          <input
            type="checkbox"
            checked={all}
            onChange={(e) => setAll(e.target.checked)}
          />
          查看全团队凭证（可撤销任意凭证）
        </label>
      )}
      {loading ? (
        <Loading />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>已签发凭证</CardTitle>
          </CardHeader>
          <CardContent>
            {!data?.length && <p>尚无凭证</p>}
            {(Array.isArray(data) ? data : []).map((item) => (
              <div key={item.id} className="flex flex-col gap-2 py-3">
                <strong>{item.name}</strong>
                <p>
                  所属成员 ID：{item.user_id} · 能力：{item.scopes.join(" / ")}
                </p>
                <p>
                  到期：{date(item.expires)} · 最后使用：{date(item.last_used)}{" "}
                  ·{" "}
                  {item.revoked
                    ? "已撤销"
                    : item.expires * 1000 <= observedAt
                      ? "已到期"
                      : "有效"}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy || !!item.revoked}
                  onClick={async () => {
                    setBusy(true);
                    setFailure(undefined);
                    try {
                      await post(`/access-credentials/${item.id}/revoke`);
                      await reload();
                    } catch (e) {
                      setFailure(e);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  撤销 {item.name}
                </Button>
                <Separator />
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}
