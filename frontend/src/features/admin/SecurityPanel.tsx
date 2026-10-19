import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { date } from "@/presentation";
import { api, post } from "@/api";
import { ErrorNotice, Loading } from "@/components/shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TabsContent } from "@/components/ui/tabs";
import { useLoad } from "@/hooks/useLoad";
import { useState } from "react";

export function SecurityPanel() {
  const { data, error, loading, reload } = useLoad(() =>
    api("/admin/master-key"),
  );
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<unknown>();
  const [message, setMessage] = useState("");
  return (
    <TabsContent value="security" className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>外置主密钥状态</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {loading ? <Loading /> : null}
          <ErrorNotice error={error} />
          {data ? (
            <dl className="grid gap-4 sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">当前代次</dt>
                <dd>{data.generation}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">可用性</dt>
                <dd>
                  {data.available ? "可用" : "不可用，请恢复正确的外置文件"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">上次轮换</dt>
                <dd>{data.rotated_at ? date(data.rotated_at) : "初始导入"}</dd>
              </div>
            </dl>
          ) : null}
          <Button variant="outline" disabled={saving} onClick={reload}>
            刷新主密钥状态
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>轮换主密钥</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="max-w-lg flex flex-col gap-4"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!data) return;
              setSaving(true);
              setFailure(undefined);
              setMessage("");
              try {
                const result = await post("/admin/master-key/rotate", {
                  password,
                  expected_generation: data.generation,
                });
                setMessage(
                  `已轮换至代次 ${result.generation}；模型凭据 ${result.counts.credential_versions} 个版本，Hub 凭据 ${result.counts.source_credentials} 个版本。`,
                );
              } catch (e) {
                setFailure(e);
              } finally {
                setPassword("");
                setSaving(false);
                reload();
              }
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="master-password">
                  当前管理员密码（重新验证）
                </FieldLabel>
                <Input
                  id="master-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  disabled={saving}
                />
              </Field>
              <Button
                type="submit"
                disabled={
                  !data || !data.available || !!error || saving || !password
                }
              >
                {saving ? "正在轮换…" : "轮换主密钥"}
              </Button>
            </FieldGroup>
          </form>
          <ErrorNotice error={failure} />
          {message ? <p role="status">{message}</p> : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>泄露处置与边界</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <ul className="list-disc ml-4 flex flex-col gap-2">
            <li>轮换不撤销上游 key 和已泄露的旧快照。</li>
            <li>不擦除旧库页、WAL、日志和备份；旧主密钥文件保留。</li>
            <li>运行中进程可能仍持有旧秘密。</li>
            <li>泄露时先按下方五步顺序处置。</li>
          </ul>
          <details className="raw-details">
            <summary>展开泄露处置五步顺序</summary>
            <ol className="list-decimal ml-4 flex flex-col gap-3">
              <li>暂停新受理；暂停不会停止已有队列。</li>
              <li>
                先停用受影响的模型 key / Hub
                凭据（该身份全部旧版本），阻止旧队列新启动。
              </li>
              <li>按需取消已运行任务，再轮换主密钥。</li>
              <li>
                在上游撤销旧凭据，再对同一身份轮换写入新值；新版本会启用。
              </li>
              <li>
                验证新实验，再恢复受理。旧队列不会自动改绑，必要时新建或重跑。
              </li>
            </ol>
          </details>
        </CardContent>
      </Card>
    </TabsContent>
  );
}
