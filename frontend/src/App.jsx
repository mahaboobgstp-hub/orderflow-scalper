
import { useState } from "react";

const initialBids = [
  { price: 78.72, quantity: 5200 },
  { price: 78.70, quantity: 4300 },
  { price: 78.68, quantity: 3800 },
  { price: 78.66, quantity: 6100 },
  { price: 78.64, quantity: 2900 },
];

const initialAsks = [
  { price: 78.75, quantity: 3100 },
  { price: 78.77, quantity: 4200 },
  { price: 78.79, quantity: 5100 },
  { price: 78.81, quantity: 2700 },
  { price: 78.83, quantity: 3900 },
];

const strategies = [
  {
    name: "Order Book Imbalance",
    description: "Compare bid and ask liquidity",
    status: "READY",
  },
  {
    name: "Liquidity Detection",
    description: "Identify unusually large orders",
    status: "PLANNED",
  },
  {
    name: "Spread Analysis",
    description: "Monitor bid-ask spread behaviour",
    status: "READY",
  },
  {
    name: "Momentum Detection",
    description: "Study short-term price movement",
    status: "PLANNED",
  },
];

function Metric({ label, value, note, color }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${color || ""}`}>{value}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}

function SectionTitle({ title, subtitle, right }) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export default function App() {
  const [activePage, setActivePage] = useState("Overview");
  const [symbol, setSymbol] = useState("IDFCFIRSTB");
  const [lastPrice, setLastPrice] = useState("78.75");
  const [bidPrice, setBidPrice] = useState("78.72");
  const [askPrice, setAskPrice] = useState("78.75");
  const [bidQty, setBidQty] = useState("5200");
  const [askQty, setAskQty] = useState("3100");
  const [analysis, setAnalysis] = useState(null);
  const [notice, setNotice] = useState("");

  const bidQuantity = Number(bidQty) || 0;
  const askQuantity = Number(askQty) || 0;
  const totalQuantity = bidQuantity + askQuantity;

  const imbalance =
    totalQuantity > 0
      ? ((bidQuantity - askQuantity) / totalQuantity) * 100
      : 0;

  const spread = Number(askPrice) - Number(bidPrice);

  function runAnalysis(event) {
    event.preventDefault();

    const last = Number(lastPrice);
    const bid = Number(bidPrice);
    const ask = Number(askPrice);
    const bq = Number(bidQty);
    const aq = Number(askQty);

    if (
      !Number.isFinite(last) ||
      !Number.isFinite(bid) ||
      !Number.isFinite(ask) ||
      !Number.isFinite(bq) ||
      !Number.isFinite(aq) ||
      last <= 0 ||
      bid <= 0 ||
      ask <= 0 ||
      bq < 0 ||
      aq < 0 ||
      ask < bid
    ) {
      setNotice("Please enter valid prices and quantities. Ask must be at least equal to bid.");
      setAnalysis(null);
      return;
    }

    const total = bq + aq;
    const bookImbalance =
      total > 0 ? ((bq - aq) / total) * 100 : 0;

    let interpretation = "Balanced displayed liquidity";
    let bias = "NEUTRAL";

    if (bookImbalance > 20) {
      interpretation = "Bid-side displayed quantity is stronger";
      bias = "BUY-SIDE PRESSURE";
    } else if (bookImbalance < -20) {
      interpretation = "Ask-side displayed quantity is stronger";
      bias = "SELL-SIDE PRESSURE";
    }

    setAnalysis({
      symbol,
      last,
      bid,
      ask,
      spread: ask - bid,
      imbalance: bookImbalance,
      interpretation,
      bias,
    });

    setNotice("Snapshot analysis completed using manual demo inputs.");
  }

  function resetAnalysis() {
    setLastPrice("78.75");
    setBidPrice("78.72");
    setAskPrice("78.75");
    setBidQty("5200");
    setAskQty("3100");
    setAnalysis(null);
    setNotice("Demo snapshot restored.");
  }

  const navItems = [
    { name: "Overview", icon: "◫" },
    { name: "Order Book", icon: "▤" },
    { name: "Strategies", icon: "⌘" },
    { name: "Analysis", icon: "⌁" },
    { name: "Settings", icon: "⚙" },
  ];

  function renderPage() {
    if (activePage === "Order Book") {
      return (
        <>
          <SectionTitle
            title="Order Book Depth"
            subtitle="Illustrative bid and ask liquidity"
          />
          <div className="panel">
            <div className="book-header">
              <span>PRICE (₹)</span>
              <span>QUANTITY</span>
            </div>
            <div className="book-columns">
              <div>
                <div className="book-side-title buy-text">BIDS</div>
                {initialBids.map((item) => (
                  <div className="book-row bid-row" key={item.price}>
                    <span>{item.price.toFixed(2)}</span>
                    <span>{item.quantity.toLocaleString("en-IN")}</span>
                  </div>
                ))}
              </div>
              <div>
                <div className="book-side-title sell-text">ASKS</div>
                {initialAsks.map((item) => (
                  <div className="book-row ask-row" key={item.price}>
                    <span>{item.price.toFixed(2)}</span>
                    <span>{item.quantity.toLocaleString("en-IN")}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="demo-disclaimer">
              Demo order book. These are not live exchange orders.
            </div>
          </div>
        </>
      );
    }

    if (activePage === "Strategies") {
      return (
        <>
          <SectionTitle
            title="Strategy Centre"
            subtitle="Research modules and development status"
          />
          <div className="strategy-grid">
            {strategies.map((strategy) => (
              <div className="panel strategy-card" key={strategy.name}>
                <div className="strategy-icon">⌘</div>
                <h3>{strategy.name}</h3>
                <p>{strategy.description}</p>
                <span
                  className={
                    strategy.status === "READY"
                      ? "status-tag ready"
                      : "status-tag planned"
                  }
                >
                  {strategy.status}
                </span>
              </div>
            ))}
          </div>
        </>
      );
    }

    if (activePage === "Analysis") {
      return (
        <>
          <SectionTitle
            title="Snapshot Analysis"
            subtitle="Enter a sample order book to calculate liquidity imbalance"
          />
          <div className="panel">
            <form onSubmit={runAnalysis} className="analysis-form">
              <label>
                Trading symbol
                <input
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  required
                />
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
              <div className="form-grid">
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
                  Best ask (₹)
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={askPrice}
                    onChange={(e) => setAskPrice(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Bid quantity
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={bidQty}
                    onChange={(e) => setBidQty(e.target.value)}
                    required
                  />
                </label>
                <label>
                  Ask quantity
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={askQty}
                    onChange={(e) => setAskQty(e.target.value)}
                    required
                  />
                </label>
              </div>
              <div className="form-actions">
                <button className="primary-button" type="submit">
                  Analyse Snapshot
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={resetAnalysis}
                >
                  Reset
                </button>
              </div>
            </form>

            {notice && <div className="notice">{notice}</div>}

            {analysis && (
              <div className="analysis-result">
                <h3>Analysis Result</h3>
                <div className="result-grid">
                  <Metric
                    label="Book Imbalance"
                    value={`${analysis.imbalance.toFixed(2)}%`}
                    note={analysis.interpretation}
                    color={analysis.imbalance >= 0 ? "positive" : "negative"}
                  />
                  <Metric
                    label="Spread"
                    value={`₹${analysis.spread.toFixed(2)}`}
                    note="Ask price minus bid price"
                  />
                  <Metric
                    label="Market Bias"
                    value={analysis.bias}
                    note="Indicative liquidity pressure only"
                  />
                  <Metric
                    label="Last Price"
                    value={`₹${analysis.last.toFixed(2)}`}
                    note={analysis.symbol}
                  />
                </div>
                <div className="demo-disclaimer">
                  This calculation is not a trading signal. Displayed
                  liquidity can change or be cancelled and does not
                  establish market direction.
                </div>
              </div>
            )}
          </div>
        </>
      );
    }

    if (activePage === "Settings") {
      return (
        <>
          <SectionTitle
            title="Application Settings"
            subtitle="Current application configuration"
          />
          <div className="panel settings-list">
            <div className="setting-row">
              <div>
                <strong>Trading mode</strong>
                <p>Live order placement is disabled</p>
              </div>
              <span className="status-tag ready">PAPER ONLY</span>
            </div>
            <div className="setting-row">
              <div>
                <strong>Data source</strong>
                <p>Local illustrative demo data</p>
              </div>
              <span className="status-tag planned">DEMO</span>
            </div>
            <div className="setting-row">
              <div>
                <strong>Backend connection</strong>
                <p>Not connected in this frontend phase</p>
              </div>
              <span className="status-tag planned">OFFLINE</span>
            </div>
            <div className="setting-row">
              <div>
                <strong>Broker integration</strong>
                <p>No broker API credentials configured</p>
              </div>
              <span className="status-tag planned">DISABLED</span>
            </div>
          </div>
        </>
      );
    }

    return (
      <>
        <SectionTitle
          title="Trading Overview"
          subtitle="Order flow research and market monitoring workspace"
          right={<span className="status-tag ready">PAPER MODE</span>}
        />

        <div className="metric-grid">
          <Metric
            label="Last Traded Price"
            value="₹78.75"
            note="Illustrative market value"
          />
          <Metric
            label="Bid Liquidity"
            value="5,200"
            note="Sample quantity"
            color="positive"
          />
          <Metric
            label="Ask Liquidity"
            value="3,100"
            note="Sample quantity"
            color="negative"
          />
          <Metric
            label="Book Imbalance"
            value="+25.29%"
            note="Calculated from sample quantities"
            color="positive"
          />
        </div>

        <div className="dashboard-grid">
          <div className="panel">
            <SectionTitle
              title="Order Book Snapshot"
              subtitle="Sample market depth"
            />
            <div className="book-header">
              <span>PRICE (₹)</span>
              <span>QUANTITY</span>
            </div>
            <div className="book-columns">
              <div>
                <div className="book-side-title buy-text">BIDS</div>
                {initialBids.slice(0, 4).map((item) => (
                  <div className="book-row bid-row" key={item.price}>
                    <span>{item.price.toFixed(2)}</span>
                    <span>{item.quantity.toLocaleString("en-IN")}</span>
                  </div>
                ))}
              </div>
              <div>
                <div className="book-side-title sell-text">ASKS</div>
                {initialAsks.slice(0, 4).map((item) => (
                  <div className="book-row ask-row" key={item.price}>
                    <span>{item.price.toFixed(2)}</span>
                    <span>{item.quantity.toLocaleString("en-IN")}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="demo-disclaimer">
              Illustrative data · Not connected to an exchange
            </div>
          </div>

          <div className="panel">
            <SectionTitle
              title="Liquidity Pressure"
              subtitle="Sample bid versus ask quantities"
            />
            <div className="liquidity-summary">
              <div className="liquidity-number buy-text">5,200</div>
              <div className="liquidity-number sell-text">3,100</div>
            </div>
            <div className="liquidity-bar">
              <div className="bid-fill" style={{ width: "62.7%" }} />
              <div className="ask-fill" style={{ width: "37.3%" }} />
            </div>
            <div className="liquidity-legend">
              <span>Bid liquidity · 62.7%</span>
              <span>Ask liquidity · 37.3%</span>
            </div>
            <div className="imbalance-box">
              <span>Sample order book imbalance</span>
              <strong className="positive">+25.29%</strong>
            </div>
            <p className="muted-copy">
              A snapshot of displayed quantities is not a guarantee of
              execution or future price movement.
            </p>
          </div>
        </div>

        <div className="panel strategy-overview">
          <SectionTitle
            title="Strategy Modules"
            subtitle="Research engine development roadmap"
            right={
              <button
                className="text-button"
                onClick={() => setActivePage("Strategies")}
              >
                View all →
              </button>
            }
          />
          {strategies.map((strategy) => (
            <div className="strategy-row" key={strategy.name}>
              <div>
                <strong>{strategy.name}</strong>
                <p>{strategy.description}</p>
              </div>
              <span
                className={
                  strategy.status === "READY"
                    ? "status-tag ready"
                    : "status-tag planned"
                }
              >
                {strategy.status}
              </span>
            </div>
          ))}
        </div>
      </>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo">OF</div>
          <div>
            <strong>ORDERFLOW</strong>
            <span>SCALPER</span>
          </div>
        </div>

        <div className="sidebar-label">WORKSPACE</div>

        <nav>
          {navItems.map((item) => (
            <button
              key={item.name}
              className={`nav-item ${
                activePage === item.name ? "active" : ""
              }`}
              onClick={() => {
                setActivePage(item.name);
                setNotice("");
              }}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.name}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="connection-indicator">
            <span className="indicator-dot" />
            Demo workspace active
          </div>
          <div className="sidebar-version">VERSION 0.2.0</div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <div className="topbar-label">ORDERFLOW RESEARCH PLATFORM</div>
            <div className="topbar-page">{activePage}</div>
          </div>
          <div className="topbar-right">
            <span className="demo-badge">DEMO DATA</span>
            <span className="paper-badge">PAPER ONLY</span>
          </div>
        </header>

        <div className="content-area">{renderPage()}</div>

        <footer className="footer">
          <span>© 2026 OrderFlow Scalper</span>
          <span>Research platform · Live trading disabled</span>
        </footer>
      </main>
    </div>
  );
}
