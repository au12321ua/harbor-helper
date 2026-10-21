import { VersionFooter } from "./VersionDialog";
import { TimezoneSettings } from "@/components/TimezoneSettings";
import { ThemeToggle } from "@/components/ThemeToggle";
import { HarborMark } from "@/components/HarborMark";
import { api, post, type User } from "@/api";
import { Button } from "@/components/ui/button";
import { useLoad } from "@/hooks/useLoad";
import {
  GitCompareArrows,
  LayoutList,
  LogOut,
  Plus,
  Settings2,
  Paperclip,
  KeyRound,
  UserRound,
  Menu,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
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
  const location = useLocation();
  const [openAt, setOpenAt] = useState<string>();
  const open = openAt === location.key;
  const setOpen = (value: boolean) =>
    setOpenAt(value ? location.key : undefined);
  const trigger = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLElement>(null);
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 768px)");
    const close = () => {
      if (desktop.matches) setOpenAt(undefined);
    };
    desktop.addEventListener("change", close);
    return () => desktop.removeEventListener("change", close);
  }, []);
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    const button = trigger.current;
    document.body.style.overflow = "hidden";
    drawer.current?.querySelector<HTMLButtonElement>("button")?.focus();
    function keydown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpenAt(undefined);
      }
      if (e.key === "Tab") {
        const items = Array.from(
          drawer.current?.querySelectorAll<HTMLElement>(
            "a, button:not(:disabled)",
          ) || [],
        );
        const first = items[0],
          last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", keydown);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", keydown);
      button?.focus();
    };
  }, [open]);
  const path = location.pathname;
  const crumb = path.startsWith("/runs/")
    ? "实验详情"
    : path.startsWith("/submissions/")
      ? "受理准备"
      : {
          "/": "共享实验",
          "/management": "请求与目录管理",
          "/operations": "请求历史",
          "/new": "新建实验",
          "/compare": "实验对比",
          "/attachments": "团队附件",
          "/admin": "团队管理",
          "/account": "账户与密码",
          "/access-credentials": "自动化凭证",
        }[path] || "页面不存在";
  return (
    <div className="app-shell">
      {open && (
        <button
          className="drawer-backdrop"
          aria-label="关闭导航遮罩"
          onClick={() => setOpen(false)}
        />
      )}
      <aside
        ref={drawer}
        className={`sidebar ${open ? "is-open" : ""}`}
        role={open ? "dialog" : undefined}
        aria-modal={open || undefined}
        aria-label="工作空间导航"
      >
        <Button
          variant="ghost"
          size="icon"
          className="drawer-close"
          aria-label="关闭导航"
          onClick={() => setOpen(false)}
        >
          <X />
        </Button>
        <Link className="brand" to="/">
          <HarborMark />
          <span>Harbor Helper</span>
        </Link>
        <nav aria-label="主导航">
          <p className="nav-label">工作空间</p>
          <NavLink
            end
            to="/"
            className={
              path === "/" ||
              path.startsWith("/runs/") ||
              path.startsWith("/submissions/")
                ? "active"
                : ""
            }
          >
            <LayoutList />
            共享实验
          </NavLink>
          <NavLink to="/new">
            <Plus />
            新建实验
          </NavLink>
          <NavLink to="/compare">
            <GitCompareArrows />
            实验对比
          </NavLink>
          <NavLink to="/management"><LayoutList />请求与目录管理</NavLink>
          <NavLink to="/operations">
            <LayoutList />
            <span>请求历史</span>
          </NavLink>
          <NavLink to="/attachments">
            <Paperclip />
            团队附件
          </NavLink>
          {user.role === "admin" && (
            <>
              <p className="nav-label">管理</p>
              <NavLink to="/admin">
                <Settings2 />
                团队管理
              </NavLink>
            </>
          )}
        </nav>
        <nav className="account-nav" aria-label="账户导航">
          <NavLink to="/account">
            <UserRound />
            账户与密码
          </NavLink>
          <NavLink to="/access-credentials">
            <KeyRound />
            自动化凭证
          </NavLink>
        </nav>
        <div className="sidebar-bottom">
          <div className="avatar">
            {String(user.username || "?")
              .slice(0, 2)
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
      <div className="workspace" inert={open || undefined}>
        <header className="topbar">
          <Button
            ref={trigger}
            className="drawer-trigger"
            variant="ghost"
            size="icon"
            aria-label="打开导航"
            aria-expanded={open}
            onClick={() => setOpen(true)}
          >
            <Menu />
          </Button>
          <span className="team-name">
            {catalog?.settings?.team_name || "团队工作空间"}
          </span>
          <span className="crumb">/　{crumb}</span>
          <div className="topbar-tools">
            <div className="timezone-control">
              <span>时区</span>
              <TimezoneSettings />
            </div>
            <ThemeToggle />
          </div>
        </header>
        <main>
          <AppRoutes user={user} onLogout={onLogout} />
        </main>
        <footer>
          <VersionFooter user={user} /> <span>全部实验团队共享</span>
        </footer>
      </div>
    </div>
  );
}
