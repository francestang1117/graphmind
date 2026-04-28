import { useMemo, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { semanticSearch, type SearchResult } from "../services/api";

const demoResults: SearchResult[] = [
  {
    title: "Neural Network",
    type: "CONCEPT",
    score: 98,
    excerpt:
      "A computational model used in machine learning to approximate functions through layers of connected nodes.",
    source: "neural-nets.pdf",
    tags: ["deep-learning", "architecture"],
  },
  {
    title: "Backpropagation",
    type: "CONCEPT",
    score: 91,
    excerpt:
      "The training algorithm that computes gradients by propagating errors backwards through neural network layers.",
    source: "neural-nets.pdf",
    tags: ["training", "gradient"],
  },
  {
    title: "TensorFlow",
    type: "FRAMEWORK",
    score: 86,
    excerpt:
      "An open-source machine learning framework commonly used for training and deploying neural networks.",
    source: "data-analysis.py",
    tags: ["python", "framework"],
  },
];

const filters = ["All", "CONCEPT", "FRAMEWORK", "PERSON"];

export default function SearchPanel() {
  const [query, setQuery] = useState("neural network");
  const [filter, setFilter] = useState("All");
  const [results, setResults] = useState<SearchResult[]>(demoResults);
  const [loading, setLoading] = useState(false);

  const visible = useMemo(() => {
    // Filter locally so demo data and future API results behave the same way.
    const q = query.trim().toLowerCase();
    return results.filter((result) => {
      const matchesFilter = filter === "All" || result.type === filter;
      const matchesQuery =
        !q ||
        result.title.toLowerCase().includes(q) ||
        result.excerpt.toLowerCase().includes(q) ||
        result.tags?.some((tag) => tag.toLowerCase().includes(q));
      return matchesFilter && matchesQuery;
    });
  }, [filter, query, results]);

  const runSearch = async (value: string) => {
    setQuery(value);
    if (!value.trim()) {
      setResults(demoResults);
      return;
    }
    setLoading(true);
    try {
      const remote = await semanticSearch(value);
      setResults(remote.length ? remote : demoResults);
    } catch {
      setResults(demoResults);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="search-panel">
      <div className="search-toolbar">
        <div className="search-box">
          <Search size={20} />
          <input
            value={query}
            onChange={(event) => runSearch(event.target.value)}
            placeholder="Search your knowledge base..."
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
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="result-list">
        {visible.length === 0 ? (
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
                <em>{result.type}</em>
                {result.tags?.map((tag) => (
                  <em key={tag}>{tag}</em>
                ))}
              </footer>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
