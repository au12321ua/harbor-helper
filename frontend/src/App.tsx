import { Shell } from "@/app/Shell";
import { useSession } from "@/app/useSession";
import { ErrorNotice } from "@/components/shared";
import { Login } from "@/features/account/Login";
import { SetupPage } from "@/features/account/SetupPage";
import { LoaderCircle } from "lucide-react";
import { BrowserRouter } from "react-router-dom";
import { ThemeToaster } from "@/components/ThemeToaster";
import "./App.css";
export default function App() {
  const { user, setUser, loading, setup, setSetup, failure, setFailure } =
    useSession();
  return (
    <BrowserRouter>
      {loading ? (
        <div className="initial-loading">
          <LoaderCircle className="animate-spin" />
          <p>正在连接团队实验室…</p>
        </div>
      ) : setup ? (
        <SetupPage
          done={() => {
            setSetup(false);
            setFailure(undefined);
          }}
        />
      ) : user ? (
        <Shell user={user} onLogout={() => setUser(null)} />
      ) : (
        <>
          <Login
            onLogin={(value) => {
              setFailure(undefined);
              setUser(value);
            }}
          />
          {failure ? (
            <div className="connection-error">
              <ErrorNotice error={failure} />
            </div>
          ) : null}
        </>
      )}
      <ThemeToaster />
    </BrowserRouter>
  );
}
