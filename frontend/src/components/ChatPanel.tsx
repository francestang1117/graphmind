import { useEffect, useMemo, useRef, useState } from "react";
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

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hello. Ask about your uploaded documents and I will answer from the current search and graph context.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const [ghostLeft, setGhostLeft] = useState(16);
  const { conversationId, files, setConversationId } = useAppStore();

  const completion = useMemo(() => {
    const term = lastMeaningfulToken(input);
    if (term.length < 2) return null;
    const match = files
      .map((file) => file.original_filename || file.filename)
      .find((name) => name.toLowerCase().startsWith(term.toLowerCase()));
    if (!match || match.toLowerCase() === term.toLowerCase()) return null;
    return { term, value: match, suffix: match.slice(term.length) };
  }, [files, input]);

  useEffect(() => {
    const width = measureRef.current?.offsetWidth ?? 0;
    setGhostLeft(16 + width);
  }, [input, completion]);

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
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "Chat is unavailable right now. Start the backend, upload documents, then try again.",
        },
      ]);
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
        <div className="chat-input-wrap">
          <span className="chat-input-measure" ref={measureRef}>{input}</span>
          {completion && (
            <span className="chat-typeahead" style={{ left: ghostLeft }}>
              {completion.suffix}
            </span>
          )}
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if ((event.key === "Tab" || event.key === "ArrowRight") && completion) {
                event.preventDefault();
                setInput(completion.value);
                return;
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            placeholder="Ask anything about your documents..."
            rows={1}
          />
        </div>
        <button disabled={!input.trim() || loading} aria-label="Send message">
          {loading ? <Loader2 className="spin" size={19} /> : <Send size={19} />}
        </button>
      </form>
    </div>
  );
}

function lastMeaningfulToken(value: string) {
  const matches = value.toLowerCase().match(/[a-z0-9][a-z0-9_-]{1,}/g);
  return matches?.at(-1) ?? "";
}
