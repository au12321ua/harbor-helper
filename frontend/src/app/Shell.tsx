import { api, post, type User } from "@/api";
import { Button } from "@/components/ui/button";
import { useLoad } from "@/hooks/useLoad";
import {
  FlaskConical,
  GitCompareArrows,
  LayoutList,
  LogOut,
  Plus,
  Settings2,
} from "lucide-react";
import { Link, NavLink } from "react-router-dom";
import { toast } from "sonner";
import { AppRoutes } from "./AppRoutes";
export function Shell({
  user,
  onLogout,
}: {
  user: User;
  onLogout: () => void;
}) {
  const { data: catalog } = useLoad(() => api("/catalog"));
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <FlaskConical />
          <span>
            Harbor<span className="brand-sub">团队实验室</span>
          </span>
        </Link>
        <nav aria-label="主导航">
          <NavLink to="/account">
            <Settings2 />
            账户与密码
          </NavLink>
          <NavLink end to="/">
            <LayoutList />
            共享实验
          </NavLink>
          <NavLink to="/new">
            <Plus />
            新建实验
          </NavLink>
          <NavLink to="/access-credentials">
            <Settings2 />
            自动化凭证
          </NavLink>
          <NavLink to="/attachments">
            <LayoutList />
            团队附件
          </NavLink>
          <NavLink to="/compare">
            <GitCompareArrows />
            实验对比
          </NavLink>
          {user.role === "admin" ? (
            <NavLink to="/admin">
              <Settings2 />
              团队管理
            </NavLink>
          ) : null}
        </nav>
        <div className="sidebar-bottom">
          <div className="avatar">
            {String(user.username || "?")
              .slice(0, 1)
              .toUpperCase()}
          </div>
          <div>
            <strong>{user.username}</strong>
            <span>{user.role === "admin" ? "管理员" : "团队成员"}</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="退出登录"
            onClick={async () => {
              try {
                await post("/auth/logout");
                onLogout();
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            <LogOut />
          </Button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>{catalog?.settings?.team_name || "团队工作空间"}</span>
          <span>全部实验共享可见</span>
        </header>
        <main>
          <AppRoutes user={user} onLogout={onLogout} />
        </main>
        <footer>
          Harbor Helper <span>共享队列 · 可追溯实验</span>
        </footer>
      </div>
    </div>
  );
}
