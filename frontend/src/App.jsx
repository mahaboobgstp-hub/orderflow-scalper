import { useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

export default function App() {
  const [lastPrice, setLastPrice] = useState("78.75");
  const [bidPrice, setBidPrice] = useState("78.72");
  const [askPrice, setAskPrice] = useState("78.75");
  const [bidQuantity, setBidQuantity] = useState("5000");
  const [askQuantity, setAskQuantity] = useState("3000");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function analyseSnapshot(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await fetch(`${API_BASE}/api/analyse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: "IDFCFIRSTB",
          last_price: Number(lastPrice),
          bid_price: Number(bidPrice),
          ask_price: Number(askPrice),
          bid_quantity: Number(bidQuantity),
          ask_quantity: Number(askQuantity)
        })
      });

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      setResult(await response.json());
    } catch (err) {
      setError(
        "Could not reach the backend. Check that the Python API is running and VITE_API_BASE_URL points to it. " +
        (err?.message || "")
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page">
      <header className="topbar">
        <div className="brand-mark">OF</div>
        <div>
          <p className="eyebrow">ORDERFLOW RESEARCH</p>
          <h1>OrderFlow Scalper</h1>
        </div>
        <span className="mode-pill">PAPER ONLY</span>
      </header>

      <section className="intro">
        <p className="eyebrow">CONTROL CENTRE</p>
        <h2>Market research dashboard</h2>
        <p>
          Starter interface for testing order-book snapshots.
          It does not connect to a broker or place orders.
        </p>
      </section>

      <section className="grid">
        <article className="panel">
          <p className="eyebrow">MANUAL TEST</p>
          <h3>Sample order book</h3>

          <form onSubmit={analyseSnapshot}>
            <label>
              Symbol
              <input value="IDFCFIRSTB" readOnly />
            </label>

            <label>
              Last traded price (₹)
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={lastPrice}
                onChange={(e) => setLastPrice(e.target.value)}
                required
              />
            </label>

            <div className="two-col">
              <label>
                Best bid (₹)
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={bidPrice}
                  onChange={(e) => setBidPrice(e.target.value)}
                  required
                />
              </label>

              <label>
                Best offer (₹)
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={askPrice}
                  onChange={(e) => setAskPrice(e.target.value)}
                  required
                />
              </label>
            </div>

            <div className="two-col">
              <label>
                Bid quantity
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={bidQuantity}
                  onChange={(e) => setBidQuantity(e.target.value)}
                  required
                />
              </label>

              <label>
                Offer quantity
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={askQuantity}
                  onChange={(e) => setAskQuantity(e.target.value)}
                  required
                />
              </label>
            </div>

            <button type="submit" disabled={loading}>
              {loading ? "Analysing..." : "Analyse snapshot"}
            </button>
          </form>
        </article>

        <article className="panel results-panel">
          <p className="eyebrow">ANALYSIS OUTPUT</p>
          <h3>Snapshot interpretation</h3>

          {!result && !error && (
            <div className="empty-state">
              <div className="empty-icon">↗</div>
              <p>Submit the sample snapshot to see the backend result.</p>
            </div>
          )}

          {error && <p className="error-message">{error}</p>}

          {result && (
            <div className="result-content">
              <div className="metric">
                <span>Book imbalance</span>
                <strong>
                  {(result.book_imbalance * 100).toFixed(2)}%
                </strong>
              </div>

              <div className="metric">
                <span>Spread</span>
                <strong>₹{Number(result.spread).toFixed(4)}</strong>
              </div>

              <div className="interpretation">
                {result.interpretation}
              </div>

              <div className="metric">
                <span>Trade action</span>
                <strong>{result.trade_action}</strong>
              </div>

              <p className="result-note">{result.note}</p>
            </div>
          )}
        </article>
      </section>

      <footer>
        <span>OrderFlow Scalper · v0.1.0</span>
        <span>Research only · Live orders disabled</span>
      </footer>
    </main>
  );
}
