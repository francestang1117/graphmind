import { useEffect, useRef, useState } from "react";
import { FileText, Loader2, Send } from "lucide-react";
import { sendChatMessage } from "../services/api";
import { useAppStore } from "../stores/appStore";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
}

const suggestions = [
  "What are the main concepts in my documents?",
  "Which frameworks appear most often?",
  "Summarize the key ideas across all files",
];

const fallbackReplies = [
  {
    content:
      "I can already show the chat workflow, but the backend chat endpoint is not implemented yet. For now, upload documents first, then build the graph/search modules in the next stage.",
    sources: ["roadmap"],
  },
  {
    content:
      "The current backend supports upload, validation, storage, listing, deletion, and document parsing. Entity extraction and graph persistence are the next natural modules.",
    sources: ["backend/app/api/endpoints/documents.py"],
  },
];

export default function ChatPanel() {
  // Chat is wired to the future API, with local replies so the workflow still feels complete.
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hello. Ask about your uploaded documents, or use this panel to preview the future RAG workflow.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [replyIndex, setReplyIndex] = useState(0);
  const bodyRef = useRef<HTMLDivElement>(null);
  const { conversationId, setConversationId } = useAppStore();

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [messages, loading]);

  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content }]);
    setLoading(true);

    try {
      const response = await sendChatMessage(content, conversationId);
      if (response.conversation_id) setConversationId(response.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: response.answer ?? "No answer returned.",
          sources: (response.sources ?? []).map((source: string | { document?: string }) =>
            typeof source === "string" ? source : source.document ?? "source",
          ),
        },
      ]);
    } catch {
      const fallback = fallbackReplies[replyIndex % fallbackReplies.length];
      setReplyIndex((value) => value + 1);
      setMessages((prev) => [...prev, { role: "assistant", ...fallback }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-messages" ref={bodyRef}>
        {messages.map((message, index) => (
          <div className={`message ${message.role}`} key={index}>
            <div className="avatar">{message.role === "assistant" ? "AI" : "U"}</div>
            <div>
              <div className="bubble">{message.content}</div>
              {message.sources?.length ? (
                <div className="source-list">
                  {message.sources.map((source) => (
                    <span key={source}>
                      <FileText size={13} />
                      {source}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {loading && (
          <div className="message assistant">
            <div className="avatar">AI</div>
            <div className="bubble muted">Searching knowledge base...</div>
          </div>
        )}
      </div>

      <div className="suggestions">
        {suggestions.map((item) => (
          <button key={item} onClick={() => send(item)}>
            {item}
          </button>
        ))}
      </div>

      <form
        className="chat-input-row"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
          placeholder="Ask anything about your documents..."
          rows={1}
        />
        <button disabled={!input.trim() || loading} aria-label="Send message">
          {loading ? <Loader2 className="spin" size={19} /> : <Send size={19} />}
        </button>
      </form>
    </div>
  );
}
