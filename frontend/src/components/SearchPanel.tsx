import { useEffect, useMemo, useState } from "react";
import { Loader2, Search, X } from "lucide-react";
import { semanticSearch, type SearchResult } from "../services/api";

const SEARCH_HISTORY_KEY = "graphmind.search.history";
const MAX_HISTORY = 8;

export default function SearchPanel() {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("All");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<string[]>(() => readSearchHistory());

  const filters = useMemo(() => {
    const types = [...new Set(results.map((result) => result.type).filter(Boolean))].sort();
    return ["All", ...types];
  }, [results]);

  const visible = useMemo(() => {
    return results
      .filter((result) => filter === "All" || result.type === filter)
      .sort((left, right) => right.score - left.score);
  }, [filter, results]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setError("");
      setLoading(false);
      return;
    }

    const timeout = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const remote = await semanticSearch(trimmed, 10, "hybrid");
        setResults(remote);
        setFilter("All");
        setHistory((current) => saveSearchHistory(trimmed, current));
      } catch {
        setResults([]);
        setError("Search is unavailable. Start the backend and upload documents first.");
      } finally {
        setLoading(false);
      }
    }, 260);

    return () => window.clearTimeout(timeout);
  }, [query]);

  const runSearch = async (value: string) => {
    setQuery(value);
  };

  const clearHistory = () => {
    window.localStorage.removeItem(SEARCH_HISTORY_KEY);
    setHistory([]);
  };

  return (
    <div className="search-panel">
      <div className="search-toolbar">
        <div className="search-box">
          <Search size={20} />
          <input
            value={query}
            onChange={(event) => runSearch(event.target.value)}
            placeholder="Search uploaded documents..."
          />
          {loading && <Loader2 className="spin" size={18} />}
        </div>
        <div className="filter-row">
          {filters.map((item) => (
            <button
              key={item}
              className={filter === item ? "active" : ""}
              onClick={() => setFilter(item)}
            >
              {formatFilterLabel(item)}
            </button>
          ))}
        </div>
        {history.length > 0 && (
          <div className="search-history">
            <span>Recent</span>
            {history.map((item) => (
              <button key={item} onClick={() => runSearch(item)}>
                {item}
              </button>
            ))}
            <button className="icon-only" onClick={clearHistory} aria-label="Clear search history" title="Clear history">
              <X size={12} />
            </button>
          </div>
        )}
      </div>

      <div className="result-list">
        {!query.trim() ? (
          <div className="empty-state search-state">
            <Search size={32} />
            <span>Search your uploaded documents</span>
            <p>Results come from parsed chunks in the local vector index.</p>
          </div>
        ) : error ? (
          <div className="empty-state search-state error">
            <Search size={32} />
            <span>{error}</span>
          </div>
        ) : !loading && visible.length === 0 ? (
          <div className="empty-state">
            <Search size={32} />
            <span>No results found</span>
          </div>
        ) : (
          visible.map((result) => (
            <article className="result-card" key={`${result.title}-${result.source}`}>
              <header>
                <strong>{result.title}</strong>
                <span>{result.score}% match</span>
              </header>
              <p>{result.excerpt}</p>
              <footer>
                <em>{result.source}</em>
                <em>{formatFilterLabel(result.type)}</em>
                {result.tags?.map((tag) => (
                  <em key={tag}>{formatTagLabel(tag)}</em>
                ))}
              </footer>
            </article>
          ))
        )}
      </div>
    </div>
  );
}

function readSearchHistory() {
  try {
    const raw = window.localStorage.getItem(SEARCH_HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string").slice(0, MAX_HISTORY) : [];
  } catch {
    return [];
  }
}

function saveSearchHistory(query: string, current: string[]) {
  const normalized = query.trim();
  if (normalized.length < 2) return current;
  const next = [normalized, ...current.filter((item) => item.toLowerCase() !== normalized.toLowerCase())].slice(0, MAX_HISTORY);
  window.localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(next));
  return next;
}

function formatFilterLabel(value: string) {
  const labels: Record<string, string> = {
    All: "All",
    SECTION: "Sections",
    SCHEMA: "Schemas",
    VALUES: "Values",
    PAGE: "Pages",
    CODE: "Code",
    TABLE: "Tables",
    TEXT: "Text",
    SUMMARY: "Summaries",
  };
  return labels[value] ?? titleCase(value);
}

function formatTagLabel(value: string) {
  return formatFilterLabel(value.toUpperCase());
}

function titleCase(value: string) {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
