import { useEffect, useState } from "react";
import {
  BookOpen,
  CircleHelp,
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
import { checkHealth } from "./services/api";
import { useAppStore } from "./stores/appStore";

type Tab = "upload" | "graph" | "search" | "chat";

const tabs: Array<{ id: Tab; label: string; title: string; icon: typeof Upload }> = [
  { id: "upload", label: "Documents", title: "Documents", icon: Upload },
  { id: "graph", label: "Graph", title: "Knowledge Graph", icon: Network },
  { id: "search", label: "Search", title: "Semantic Search", icon: Search },
  { id: "chat", label: "AI Chat", title: "AI Chat", icon: MessageSquare },
];

function App() {
  // Keep tab state local; cross-panel data lives in the small Zustand store.
  const [activeTab, setActiveTab] = useState<Tab>("upload");
  const { files, backendOnline, setBackendOnline, graphStats } = useAppStore();
  const active = tabs.find((tab) => tab.id === activeTab) ?? tabs[0];

  useEffect(() => {
    checkHealth()
      .then(() => setBackendOnline(true))
      .catch(() => setBackendOnline(false));
  }, [setBackendOnline]);

  return (
    <div className="kw-shell">
      <aside className="kw-sidebar">
        <div className="kw-brand">
          <div className="kw-logo">
            <Zap size={21} />
          </div>
          <span>KnowledgeWeave</span>
        </div>

        <nav className="kw-nav" aria-label="Primary">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                className={`kw-nav-item ${activeTab === tab.id ? "active" : ""}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon size={24} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="kw-side-footer">
          <div className={`kw-status ${backendOnline ? "online" : "offline"}`}>
            <span />
            {backendOnline ? "Backend online" : "Backend offline"}
          </div>
          <div className="kw-stats">
            <div>
              <strong>{graphStats?.total_nodes ?? 24}</strong>
              <span>nodes</span>
            </div>
            <div>
              <strong>{graphStats?.total_edges ?? 18}</strong>
              <span>edges</span>
            </div>
            <div>
              <strong>{files.length}</strong>
              <span>docs</span>
            </div>
          </div>
        </div>
      </aside>

      <main className="kw-main">
        <header className="kw-topbar">
          <h1>{active.title}</h1>
          <div className="kw-top-actions">
            <a className="kw-doc-button" href="http://localhost:8000/docs" target="_blank">
              <BookOpen size={18} />
              View docs
            </a>
            <button className="kw-icon-button" aria-label="Help">
              <CircleHelp size={20} />
            </button>
            <button className="kw-icon-button" aria-label="More">
              <MoreHorizontal size={22} />
            </button>
          </div>
        </header>

        <section className="kw-content">
          {activeTab === "upload" && <UploadPanel />}
          {activeTab === "graph" && <GraphPanel />}
          {activeTab === "search" && <SearchPanel />}
          {activeTab === "chat" && <ChatPanel />}
        </section>
      </main>
    </div>
  );
}

export default App;
