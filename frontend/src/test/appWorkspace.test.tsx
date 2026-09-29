import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

const api = vi.hoisted(() => ({
  AUTH_REQUIRED_EVENT: "graphmind:auth-required",
  checkHealth: vi.fn(),
  listWorkspaces: vi.fn(),
}));

const appStore = vi.hoisted(() => ({
  useAppStore: vi.fn(),
}));

const authStore = vi.hoisted(() => ({
  useAuthStore: vi.fn(),
}));

vi.mock("../services/api", () => api);
vi.mock("../stores/appStore", () => appStore);
vi.mock("../stores/authStore", () => authStore);
vi.mock("../components/UploadPanel", () => ({ default: () => <div data-testid="upload-panel" /> }));
vi.mock("../components/GraphPanel", () => ({ default: () => <div data-testid="graph-panel" /> }));
vi.mock("../components/SearchPanel", () => ({ default: () => <div data-testid="search-panel" /> }));
vi.mock("../components/ChatPanel", () => ({ default: () => <div data-testid="chat-panel" /> }));
vi.mock("../components/AuthControl", () => ({
  default: () => <button type="button">Sign in</button>,
}));
vi.mock("../components/AuthDialog", () => ({
  default: ({ open }: { open: boolean }) => (
    open ? <div role="dialog" aria-label="Sign in required" /> : null
  ),
}));
vi.mock("../components/VisitPreparationPanel", () => ({
  default: ({ workspaceId }: { workspaceId: string | null }) => (
    <div data-testid="visit-prep-panel" data-workspace-id={workspaceId ?? ""} />
  ),
}));
vi.mock("../components/DiseaseProfilePanel", () => ({
  default: ({ workspaceId }: { workspaceId: string | null }) => (
    <div data-testid="research-profile-panel" data-workspace-id={workspaceId ?? ""} />
  ),
}));
vi.mock("../components/DiseaseGuidePage", () => ({
  default: () => <div data-testid="disease-guide-page" />,
}));

const workspace = {
  id: "local-dev",
  user_id: "local-dev",
  name: "Local development",
  research_question: "",
  domain: "",
  status: "active",
  created_at: "2026-09-30T00:00:00Z",
  updated_at: "2026-09-30T00:00:00Z",
};

function configureAuth(user: { id: string } | null) {
  authStore.useAuthStore.mockReturnValue({
    user,
    ready: true,
    restore: vi.fn(),
  });
}

describe("App workspace loading", () => {
  beforeEach(() => {
    api.checkHealth.mockResolvedValue({ status: "healthy" });
    appStore.useAppStore.mockReturnValue({
      backendOnline: true,
      setBackendOnline: vi.fn(),
      setFiles: vi.fn(),
      setGraphStats: vi.fn(),
      setConversationId: vi.fn(),
    });
    vi.clearAllMocks();
    api.checkHealth.mockResolvedValue({ status: "healthy" });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads the local-dev workspace for an anonymous local-mode visitor", async () => {
    configureAuth(null);
    api.listWorkspaces.mockResolvedValue([workspace]);
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole("button", { name: "我的研究项目" }));

    await waitFor(() => expect(api.listWorkspaces).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("research-profile-panel")).toHaveAttribute(
      "data-workspace-id",
      "local-dev",
    );
    expect(screen.getByRole("option", { name: "Local development" })).toBeInTheDocument();
  });

  it("clears the previous workspace and shows sign-in guidance after a guest 401", async () => {
    let currentUser: { id: string } | null = { id: "previous-user" };
    authStore.useAuthStore.mockImplementation(() => ({
      user: currentUser,
      ready: true,
      restore: vi.fn(),
    }));
    api.listWorkspaces.mockResolvedValueOnce([workspace]).mockImplementationOnce(() => {
      window.dispatchEvent(new Event(api.AUTH_REQUIRED_EVENT));
      return Promise.reject(new Error("unauthorized"));
    });
    const user = userEvent.setup();
    const view = render(<App />);

    await user.click(screen.getByRole("button", { name: "我的研究项目" }));
    await waitFor(() => expect(screen.getByRole("option", { name: "Local development" })).toBeInTheDocument());

    currentUser = null;
    view.rerender(<App />);

    await waitFor(() => expect(api.listWorkspaces).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Sign in required" })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: "Local development" })).not.toBeInTheDocument();
    expect(screen.getByTestId("research-profile-panel")).toHaveAttribute("data-workspace-id", "");
  });
});
