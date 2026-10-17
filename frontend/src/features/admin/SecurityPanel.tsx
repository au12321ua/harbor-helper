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
    <TabsContent value="security">
      <h2>外置主密钥</h2>
      {loading ? <Loading /> : null}
      <ErrorNotice error={error || failure} />
      {data ? (
        <p>
          当前代次：{data.generation} ·{" "}
          {data.available ? "可用" : "不可用，请恢复正确的外置文件"} ·
          上次轮换：
          {data.rotated_at
            ? new Date(data.rotated_at * 1000).toLocaleString()
            : "初始导入"}
        </p>
      ) : null}
      <Button variant="outline" disabled={saving} onClick={reload}>
        刷新主密钥状态
      </Button>
      <form
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
        <label htmlFor="master-password">当前管理员密码（重新验证）</label>
        <Input
          id="master-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={saving}
        />
        <Button
          type="submit"
          disabled={!data || !data.available || !!error || saving || !password}
        >
          {saving ? "正在轮换…" : "轮换主密钥"}
        </Button>
      </form>
      {message ? <p role="status">{message}</p> : null}
      <h3>泄露处置顺序</h3>
      <ol className="list-disc ml-4">
        <li>暂停新受理；暂停不会停止已有队列。</li>
        <li>
          先停用受影响的模型 key / Hub
          凭据（该身份全部旧版本），阻止旧队列新启动。
        </li>
        <li>按需取消已运行任务，再轮换主密钥。</li>
        <li>在上游撤销旧凭据，再对同一身份轮换写入新值；新版本会启用。</li>
        <li>验证新实验，再恢复受理。旧队列不会自动改绑，必要时新建或重跑。</li>
      </ol>
      <p>
        主密钥轮换保留所有业务版本与绑定，不会撤销已泄露的旧快照或上游
        key，也不擦除 SQLite
        旧页、WAL、日志和备份。已运行进程可能仍持有旧秘密；请同时处置上游凭据和运行任务。旧主密钥文件保留，按备份保留策略由部署者处理。
      </p>
    </TabsContent>
  );
}
