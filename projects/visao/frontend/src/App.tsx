import { useCallback, useEffect, useState } from "react";
import { Dashboard } from "./components/Dashboard";
import { FormWorkspace } from "./components/FormWorkspace";
import { Home, type ModuleId } from "./components/Home";
import { Login } from "./components/Login";
import { Studio } from "./components/Studio";
import { SettingsWorkspace } from "./components/settings/SettingsWorkspace";
import { api, type SessionUser } from "./form/api";
import { applyPreferences, settingsAPI } from "./settings/api";
import { emptyPayload } from "./form/schema";
import type { Submission, SubmissionSummary } from "./form/types";

type Screen =
  | { name: "home" }
  | { name: "atendimentos" }
  | { name: "studio" }
  | { name: "settings" }
  | { name: "form"; submission: Submission | null };

export function App() {
  const [checkingSession, setCheckingSession] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [currentUser, setCurrentUser] = useState<SessionUser | null>(null);
  const [screen, setScreen] = useState<Screen>({ name: "home" });
  const [studioMounted, setStudioMounted] = useState(false);
  const [items, setItems] = useState<SubmissionSummary[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [globalError, setGlobalError] = useState("");

  const loadItems = useCallback(async () => {
    setLoadingItems(true);
    setGlobalError("");
    try {
      const result = await api.list();
      setItems(result.items);
    } catch (reason) {
      setGlobalError(reason instanceof Error ? reason.message : "Não foi possível carregar os atendimentos.");
    } finally {
      setLoadingItems(false);
    }
  }, []);

  useEffect(() => {
    void api.session().then((result) => {
      setAuthenticated(result.authenticated);
      setCurrentUser(result.user);
      if (result.authenticated && result.user?.capabilities?.includes("settings.view")) {
        void settingsAPI.preferences().then(applyPreferences).catch(() => undefined);
      }
    }).finally(() => setCheckingSession(false));
  }, []);

  useEffect(() => {
    if (checkingSession) return;
    let frame = 0;
    const reveal = () => {
      frame = requestAnimationFrame(() => {
        document.documentElement.classList.remove("app-prepaint");
        document.documentElement.classList.add("app-ready");
      });
    };
    const timer = window.setTimeout(reveal, Math.max(0, 1750 - performance.now()));
    return () => {
      window.clearTimeout(timer);
      cancelAnimationFrame(frame);
    };
  }, [checkingSession]);

  async function logout() {
    await api.logout().catch(() => undefined);
    setAuthenticated(false);
    setCurrentUser(null);
    setScreen({ name: "home" });
    setStudioMounted(false);
    setItems([]);
  }

  function openModule(id: ModuleId) {
    if (id === "atendimentos") {
      setGlobalError("");
      setScreen({ name: "atendimentos" });
      void loadItems();
    }
    if (id === "studio") {
      setGlobalError("");
      setStudioMounted(true);
      setScreen({ name: "studio" });
    }
    if (id === "settings") {
      setGlobalError("");
      setScreen({ name: "settings" });
    }
  }

  async function open(id: string) {
    setGlobalError("");
    try {
      const submission = await api.get(id);
      setScreen({ name: "form", submission });
    } catch (reason) {
      setGlobalError(reason instanceof Error ? reason.message : "Não foi possível abrir o atendimento.");
    }
  }

  if (checkingSession) return null;
  if (!authenticated) return <Login />;

  function nonStudioScreen() {
    if (screen.name === "form") {
      return <FormWorkspace
        key={screen.submission?.id || "new"}
        initial={screen.submission}
        initialPayload={screen.submission?.payload || emptyPayload()}
        onBack={() => { setScreen({ name: "atendimentos" }); void loadItems(); }}
        onLogout={() => void logout()}
      />;
    }
    if (screen.name === "home") {
      return <Home user={currentUser} onOpenModule={openModule} onLogout={() => void logout()} />;
    }
    if (screen.name === "atendimentos") {
      return <>
        {globalError && <div className="global-error" role="alert">{globalError}</div>}
        <Dashboard
          items={items}
          loading={loadingItems}
          user={currentUser}
          onCreate={() => setScreen({ name: "form", submission: null })}
          onOpen={(id) => void open(id)}
          onBack={() => { setGlobalError(""); setScreen({ name: "home" }); }}
          onLogout={() => void logout()}
        />
      </>;
    }
    if (screen.name === "settings") {
      return <SettingsWorkspace
        user={currentUser}
        onBack={() => setScreen({ name: "home" })}
        onLogout={() => void logout()}
      />;
    }
    return null;
  }

  return <>
    {screen.name !== "studio" && nonStudioScreen()}
    {studioMounted && (
      <div key="studio-runtime" hidden={screen.name !== "studio"}>
        <Studio user={currentUser} onBack={() => setScreen({ name: "home" })} onLogout={() => void logout()} />
      </div>
    )}
  </>;
}
