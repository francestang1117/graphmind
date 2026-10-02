import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  BookOpen,
  ClipboardList,
  CircleHelp,
  Compass,
  FolderSearch,
  MessageSquare,
  MoreHorizontal,
  Network,
  Search,
  Upload,
  Zap,
} from "lucide-react";
import UploadPanel from "./components/UploadPanel";
import GraphPanel from "./components/GraphPanel";
import SearchPanel from "./components/SearchPanel";
import ChatPanel from "./components/ChatPanel";
import AuthControl from "./components/AuthControl";
import AuthDialog from "./components/AuthDialog";
import { AUTH_REQUIRED_EVENT, checkHealth, listWorkspaces, type WorkspaceInfo } from "./services/api";
import { useAppStore } from "./stores/appStore";
import { useAuthStore } from "./stores/authStore";
import VisitPreparationPanel from "./components/VisitPreparationPanel";
import DiseaseProfilePanel from "./components/DiseaseProfilePanel";
import DiseaseGuidePage from "./components/DiseaseGuidePage";

type Tab = "explore" | "upload" | "graph" | "search" | "chat" | "disease-profiles" | "visit-prep";
type NavTab = { id: Tab; label: string; title: string; icon: typeof Upload };

const primaryTabs: NavTab[] = [
  { id: "explore", label: "了解疾病", title: "了解疾病", icon: Compass },
  { id: "upload", label: "我的资料", title: "我的资料", icon: Upload },
];

const researchTabs: NavTab[] = [
  { id: "disease-profiles", label: "我的研究项目", title: "我的研究项目", icon: FolderSearch },
  { id: "search", label: "搜索我的资料", title: "搜索我的资料", icon: Search },
  { id: "graph", label: "知识图谱", title: "Knowledge Graph", icon: Network },
  { id: "chat", label: "AI Chat", title: "AI Chat", icon: MessageSquare },
  { id: "visit-prep", label: "就诊准备", title: "Visit Preparation", icon: ClipboardList },
];

const tabTitles: Record<Tab, string> = {
  explore: "了解疾病",
  upload: "我的资料",
  graph: "Knowledge Graph",
  search: "搜索我的资料",
  chat: "AI Chat",
  "disease-profiles": "Disease Research Profiles",
  "visit-prep": "Visit Preparation",
};

function App() {
  // Keep tab state local; cross-panel data lives in the small Zustand store.
  const [activeTab, setActiveTab] = useState<Tab>("explore");
  const [authOpen, setAuthOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [workspaceEpoch, setWorkspaceEpoch] = useState(0);
  const [loadedWorkspaceScope, setLoadedWorkspaceScope] = useState<string | null>(null);
  const { backendOnline, setBackendOnline, setFiles, setGraphStats, setConversationId } = useAppStore();
  const {
    user,
    ready: authReady,
    restore,
    logoutInProgress = false,
    sessionVersion = 0,
  } = useAuthStore();
  const needsWorkspace = activeTab === "disease-profiles" || activeTab === "visit-prep";
  const workspaceScope = `${activeTab}:${user?.id ?? "guest"}:${sessionVersion}:${workspaceEpoch}`;
  const workspaceScopeRef = useRef(workspaceScope);
  useLayoutEffect(() => {
    workspaceScopeRef.current = workspaceScope;
  }, [workspaceScope]);
  const workspaceIsCurrent = !logoutInProgress && loadedWorkspaceScope === workspaceScope;
  const visibleWorkspaces = workspaceIsCurrent ? workspaces : [];
  const visibleWorkspaceId = workspaceIsCurrent ? activeWorkspaceId : null;

  const selectTab = (tab: Tab) => {
    if (needsWorkspace || tab === "disease-profiles" || tab === "visit-prep") {
      setWorkspaceEpoch((current) => current + 1);
    }
    setActiveTab(tab);
  };

  useEffect(() => {
    checkHealth()
      .then(() => setBackendOnline(true))
      .catch(() => setBackendOnline(false));
  }, [setBackendOnline]);

  useEffect(() => {
    void restore();
  }, [restore]);

  useEffect(() => {
    const showSignIn = () => setAuthOpen(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, showSignIn);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, showSignIn);
  }, []);

  useEffect(() => {
    setFiles([]);
    setGraphStats(null);
    setConversationId(null);
  }, [user?.id, setFiles, setGraphStats, setConversationId]);

  useEffect(() => {
    if (!authReady) return undefined;
    if (!needsWorkspace || logoutInProgress) return undefined;

    let cancelled = false;
    const requestScope = workspaceScope;
    const requestUserId = user?.id ?? null;
    listWorkspaces()
      .then((items) => {
        if (cancelled || workspaceScopeRef.current !== requestScope) return;
        const scopedItems = requestUserId
          ? items.filter((item) => item.user_id === requestUserId)
          : items.filter((item) => item.id === "local-dev" || item.user_id === "local-dev");
        setWorkspaces(scopedItems);
        setLoadedWorkspaceScope(requestScope);
        setActiveWorkspaceId((current) => (
          current && scopedItems.some((item) => item.id === current)
            ? current
            : scopedItems[0]?.id ?? null
        ));
      })
      .catch(() => {
        if (!cancelled && workspaceScopeRef.current === requestScope) {
          setWorkspaces([]);
          setLoadedWorkspaceScope(requestScope);
          setActiveWorkspaceId(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [authReady, needsWorkspace, logoutInProgress, user?.id, workspaceScope]);

  return (
    <div className="kw-shell">
      <aside className="kw-sidebar">
        <div className="kw-brand">
          <div className="kw-logo">
            <Zap size={21} />
          </div>
          <span>GraphMind</span>
        </div>

        <nav className="kw-nav" aria-label="Primary">
          {primaryTabs.map((tab) => <NavItem key={tab.id} tab={tab} activeTab={activeTab} onSelect={selectTab} />)}
          <div className="kw-nav-section">
            <span className="kw-nav-section-label">研究工具</span>
            {researchTabs.map((tab) => <NavItem key={tab.id} tab={tab} activeTab={activeTab} onSelect={selectTab} />)}
          </div>
        </nav>

        <div className="kw-side-footer">
          <details className="kw-developer-tools">
            <summary>开发者</summary>
            <div className={`kw-status ${backendOnline ? "online" : "offline"}`}>
              <span />
              {backendOnline ? "Backend online" : "Backend offline"}
            </div>
            <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
              <BookOpen size={14} /> API docs
            </a>
          </details>
        </div>
      </aside>

      <main className="kw-main">
        <header className="kw-topbar">
          <h1>{tabTitles[activeTab]}</h1>
          <div className="kw-top-actions">
            {(activeTab === "visit-prep" || activeTab === "disease-profiles") && (
              <label className="kw-workspace-picker">
                  <span>Research project</span>
                  <select
                    aria-label="Research project"
                    value={visibleWorkspaceId ?? ""}
                    onChange={(event) => setActiveWorkspaceId(event.target.value || null)}
                  >
                  {visibleWorkspaces.length === 0 && <option value="">No projects</option>}
                  {visibleWorkspaces.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
                  ))}
                </select>
              </label>
            )}
            <AuthControl onSignIn={() => setAuthOpen(true)} />
            <button className="kw-icon-button" aria-label="Help">
              <CircleHelp size={20} />
            </button>
            <button className="kw-icon-button" aria-label="More">
              <MoreHorizontal size={22} />
            </button>
          </div>
        </header>

        <section className="kw-content">
          <div
            className={`kw-workspace ${activeTab === "explore" ? "kw-workspace-guide" : ""}`}
            key={user?.id ?? "local-dev"}
          >
            {activeTab === "explore" && (
              <DiseaseGuidePage
                onOpenMySources={() => setActiveTab("upload")}
              />
            )}
            {activeTab === "upload" && <UploadPanel />}
            {activeTab === "graph" && <GraphPanel />}
            {activeTab === "search" && <SearchPanel />}
            {activeTab === "chat" && <ChatPanel />}
            {activeTab === "disease-profiles" && (
              <DiseaseProfilePanel
                key={`${workspaceScope}:${visibleWorkspaceId ?? "none"}`}
                workspaceId={visibleWorkspaceId}
                onOpenVisitPrep={() => setActiveTab("visit-prep")}
              />
            )}
            {activeTab === "visit-prep" && (
              <VisitPreparationPanel
                key={`${workspaceScope}:${visibleWorkspaceId ?? "none"}`}
                workspaceId={visibleWorkspaceId}
              />
            )}
          </div>
        </section>
      </main>
      <AuthDialog open={authOpen} onClose={() => setAuthOpen(false)} />
    </div>
  );
}

function NavItem({
  tab,
  activeTab,
  onSelect,
}: {
  tab: NavTab;
  activeTab: Tab;
  onSelect: (tab: Tab) => void;
}) {
  const Icon = tab.icon;
  return (
    <button
      type="button"
      className={`kw-nav-item ${activeTab === tab.id ? "active" : ""}`}
      onClick={() => onSelect(tab.id)}
    >
      <Icon size={20} />
      <span>{tab.label}</span>
    </button>
  );
}

export default App;
