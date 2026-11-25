import { useEffect, useMemo, useState } from "react";

const NAV = [
  { key: "dashboard", label: "Dashboard", icon: "⌂" },
  { key: "activity", label: "Live Activity", icon: "◷" },
  { key: "positions", label: "Positions & Trades", icon: "▤" },
  { key: "watchlist", label: "Watchlist", icon: "☆" },
  { key: "controls", label: "Controls & Settings", icon: "⚙" },
];
const CONFIG_FIELDS = [
  ["risk_per_trade_pct", "Risk per trade (%)", 0.01, 5, 0.01],
  ["max_daily_loss_pct", "Daily loss limit (%)", 0.1, 20, 0.1],
  ["max_open_positions", "Maximum open positions", 1, 50, 1],
  ["max_leverage", "Maximum leverage", 1, 5, 1],
  ["max_total_exposure_pct", "Max total exposure (%)", 1, 100, 1],
  ["max_trades_per_day", "Max trades per day", 1, 500, 1],
  ["max_consecutive_losses", "Loss streak limit", 1, 20, 1],
  ["min_risk_reward", "Minimum risk/reward", 0.1, 20, 0.1],
  ["cooldown_seconds", "Cooldown (seconds)", 0, 86400, 30],
  ["trailing_stop_pct", "Trailing stop distance (%)", 0.05, 50, 0.05],
  ["trailing_take_profit_activation_pct", "Trailing TP activation (%)", 0.05, 50, 0.05],
  ["trailing_take_profit_pct", "Trailing TP distance (%)", 0.05, 50, 0.05],
  ["min_opportunity_score", "Minimum opportunity score", 0, 100, 1],
  ["min_liquidity_usd", "Minimum liquidity (USD)", 0, 10000000000, 1000],
  ["min_24h_volume_usd", "Minimum 24h volume (USD)", 0, 10000000000, 10000],
  ["scanner_interval_seconds", "Scanner interval (seconds)", 5, 600, 5],
  ["max_watchlist_symbols", "Maximum watchlist symbols", 1, 200, 1],
];
const EMPTY = "--";
const timeText = (v) => v ? new Date(typeof v === "number" && v < 1e12 ? v * 1000 : v).toLocaleTimeString() : "--";
const labelEvent = (e) => String(e?.event || e?.type || e?.name || "event").replaceAll("_", " ");
const value = (v) => v == null ? EMPTY : v;
const money = (v) => Number.isFinite(Number(v)) ? Number(v).toLocaleString(undefined,{style:"currency",currency:"USD",maximumFractionDigits:2}) : EMPTY;

export default function App() {
  const [page, setPage] = useState("dashboard");
  const [apiBase, setApiBase] = useState(localStorage.getItem("ofs_api") || "");
  const [token, setToken] = useState(localStorage.getItem("ofs_token") || "");
  const [connected, setConnected] = useState(false);
  const [health, setHealth] = useState(null);
  const [diagnostics, setDiagnostics] = useState(null);
  const [exchanges, setExchanges] = useState(null);
  const [paper, setPaper] = useState(null);
  const [history, setHistory] = useState(null);
  const [control, setControl] = useState(null);
  const [events, setEvents] = useState([]);
  const [scanner, setScanner] = useState(null);
  const [configDraft, setConfigDraft] = useState({});
  const [symbolInput, setSymbolInput] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const base = apiBase.trim().replace(/\/$/, "");

  async function api(path, options = {}) {
    if (!base) throw new Error("Enter your backend API URL in Controls & Settings.");
    const headers = { ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (token) headers["X-Control-Token"] = token;
    const response = await fetch(base + path, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.message || "API request failed (" + response.status + ")");
    return data;
  }

  async function refreshAll() {
    if (!base) { setConnected(false); return; }
    const [h,d,x,p,controlStatus,controlLog,tradeHistory,monitorLog] = await Promise.allSettled([
      api("/health"), api("/api/monitoring/diagnostics"), api("/api/exchanges/status"),
      api("/api/paper/account"), api("/api/control/status"), api("/api/control/events"),
      api("/api/paper/history?limit=50"), api("/api/monitoring/events?limit=100")
    ]);
    if (h.status === "fulfilled") { setHealth(h.value); setConnected(true); } else { setHealth(null); setConnected(false); }
    setDiagnostics(d.status==="fulfilled" ? d.value : null);
    setExchanges(x.status==="fulfilled" ? x.value : null);
    setPaper(p.status==="fulfilled" ? p.value : null);
    if (controlStatus.status==="fulfilled") { setControl(controlStatus.value); setConfigDraft(prev => Object.keys(prev).length ? prev : (controlStatus.value.config || {})); }
    const controlEvents=controlLog.status==="fulfilled" ? controlLog.value.events || [] : [];
    const monitoringEvents=monitorLog.status==="fulfilled" ? monitorLog.value.events || [] : [];
    setEvents([...controlEvents,...monitoringEvents].sort((a,b)=>(b.timestamp||0)-(a.timestamp||0)).slice(0,100));
    setHistory(tradeHistory.status==="fulfilled" ? tradeHistory.value : null);
  }

  async function refreshScanner() {
    if (!base) return;
    try { const result = await api("/api/scanner/coins?limit=15&include_rejected=false"); setScanner(result); }
    catch { setScanner(null); }
  }

  useEffect(() => {
    localStorage.setItem("ofs_api", apiBase);
    localStorage.setItem("ofs_token", token);
    refreshAll();
    refreshScanner();
    const timer = setInterval(refreshAll, 10000);
    const scanTimer = setInterval(refreshScanner, 45000);
    return () => { clearInterval(timer); clearInterval(scanTimer); };
  }, [apiBase, token]);

  async function command(cmd) {
    setBusy(true); setNotice("");
    try {
      const result = await api("/api/control/engine", { method:"POST", body:JSON.stringify({command:cmd}) });
      setNotice(result.message || "Command accepted.");
      await refreshAll();
    } catch (e) { setNotice(e.message); }
    finally { setBusy(false); }
  }
  async function saveConfig() {
    setBusy(true); setNotice("");
    try {
      const result = await api("/api/control/config", { method:"PUT", body:JSON.stringify({config:configDraft}) });
      setNotice(result.message || "Configuration response received.");
      setControl((prev) => ({...prev, config:result.config}));
    } catch(e) { setNotice(e.message); }
    finally { setBusy(false); }
  }
  async function addCoin() {
    const symbol=symbolInput.trim().toUpperCase();
    if (!symbol) return;
    setBusy(true);
    try { const r=await api("/api/control/watchlist/add",{method:"POST",body:JSON.stringify({symbol})}); setControl(prev=>({...prev,watchlist:r.watchlist})); setSymbolInput(""); setNotice(symbol+" added to watchlist."); }
    catch(e){setNotice(e.message)} finally {setBusy(false)}
  }
  async function removeCoin(symbol) {
    setBusy(true);
    try { const r=await api("/api/control/watchlist/remove",{method:"POST",body:JSON.stringify({symbol})}); setControl(prev=>({...prev,watchlist:r.watchlist})); setNotice(symbol+" removed."); }
    catch(e){setNotice(e.message)} finally {setBusy(false)}
  }

  const openPositions = paper?.positions || [];
  const closed = history?.closed_trades || [];
  const totalPnl = Number(paper?.realized_pnl || 0) + Number(paper?.unrealized_pnl || 0);
  const engineLabel = control?.engine_state || "UNKNOWN";
  const isLiveFeed = Boolean(exchanges && Object.values(exchanges).some(x=>x?.connected || x?.status==="connected"));
  const opportunities = scanner?.markets || scanner?.coins || scanner?.results || scanner?.data || [];
  const displayEvents = useMemo(()=>events.slice(0,60),[events]);

  function header(title, subtitle) {
    return <div className="page-heading"><div><p className="eyebrow">ORDERFLOW SCALPER · OPERATOR CONSOLE</p><h1>{title}</h1><p className="subtitle">{subtitle}</p></div><div className="live-badge"><span className={connected?"dot green":"dot red"}/>{connected?"API CONNECTED":"API OFFLINE"}</div></div>;
  }
  function stat(label, val, foot, tone="") {
    return <div className="stat-card"><span className="stat-label">{label}</span><strong className={tone}>{value(val)}</strong><small>{foot || ""}</small></div>;
  }
  function renderDashboard() {
    return <>
      {header("Dashboard","A concise live view of the trading system")}
      <div className="status-strip">
        <div><span className={connected?"dot green":"dot red"}/><b>{connected?"Backend reachable":"Backend unavailable"}</b></div>
        <span className="status-chip">{engineLabel}</span><span className="status-chip paper">PAPER ONLY</span>
      </div>
      {!connected && <div className="notice warning">Backend is not connected. Enter the API URL under Controls & Settings. No live exchange data or engine state is available yet.</div>}
      {diagnostics && diagnostics.status !== "ok" && <div className="notice warning">Backend reports degraded component initialization. Check Diagnostics.</div>}
      <div className="stats-grid">
        {stat("Total P&L", money(totalPnl), "Realized + unrealized from paper account", totalPnl>=0?"positive":"negative")}
        {stat("Open Positions", openPositions.length, "Paper positions")}
        {stat("Qualified Scanner Results", scanner?.candidate_count ?? opportunities.length, "Candidate coins returned")}
        {stat("Closed Trades", closed.length, "History returned by backend")}
      </div>
      <div className="panel">
        <div className="panel-title"><h2>Engine Controls</h2><span className="subtle">Command state is backend-confirmed</span></div>
        <div className="control-buttons">
          <button className="btn primary" onClick={()=>command("START")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Start</button>
          <button className="btn warn" onClick={()=>command("PAUSE")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Pause New Entries</button>
          <button className="btn secondary" onClick={()=>command("RESUME")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Resume</button>
          <button className="btn danger" onClick={()=>command("STOP")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Stop</button>
          <button className="btn danger-outline" onClick={()=>command("EMERGENCY_HALT")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Emergency Halt</button>
        </div>
        {!control?.autonomous_engine_integrated && <p className="notice warning">Autonomous strategy/execution loop is not yet integrated. Start is intentionally blocked by the backend.</p>}
      </div>
      <div className="split-grid">
        <div className="panel"><div className="panel-title"><h2>Open Positions</h2><button className="link-button" onClick={()=>setPage("positions")}>View all</button></div>
          {openPositions.length===0 ? <div className="empty-state">No open paper positions returned.</div> : openPositions.slice(0,5).map(p=><div className="list-row" key={p.symbol}><div><b>{p.symbol}</b><small>{String(p.side||"").toUpperCase()} · {p.quantity}</small></div><div className="align-right"><b>{money(p.unrealized_pnl)}</b><small>Mark: {value(p.mark_price)}</small></div></div>)}
        </div>
        <div className="panel"><div className="panel-title"><h2>Backend & Feed</h2><button className="link-button" onClick={()=>setPage("controls")}>Details</button></div>
          <div className="list-row"><div><b>API Health</b><small>Last refresh {timeText(Date.now())}</small></div><span className={connected?"status-chip good":"status-chip bad"}>{connected?"OK":"OFFLINE"}</span></div>
          <div className="list-row"><div><b>Market feeds</b><small>Exchange connection manager</small></div><span className="status-chip">{isLiveFeed?"CONNECTED":"UNKNOWN"}</span></div>
          <div className="list-row"><div><b>Diagnostics</b><small>Component initialization</small></div><span className="status-chip">{diagnostics?.status || "N/A"}</span></div>
        </div>
      </div>
      <div className="panel"><div className="panel-title"><h2>Scanner Candidates</h2><button className="link-button" onClick={refreshScanner}>Refresh scanner</button></div><div className="subtle">Public Binance scanner · ranking only, not trading signals</div>{opportunities.length===0?<div className="empty-state">No candidates returned or scanner unavailable.</div>:opportunities.slice(0,8).map((coin,i)=><div className="list-row" key={coin.symbol||i}><div><b>{coin.symbol}</b><small>{coin.activity_acceleration_label||"Activity"} · {value(coin.price_change_24h_pct)}% 24h change</small></div><div className="align-right"><b>{value(coin.suitability_score)}</b><small>Suitability score</small></div></div>)}</div>
      <div className="panel"><div className="panel-title"><h2>Recent Engine Events</h2><button className="link-button" onClick={()=>setPage("activity")}>View activity</button></div>{displayEvents.length===0?<div className="empty-state">No operator events yet.</div>:displayEvents.slice(0,8).map((e,i)=><div className="event-row" key={i}><span className="event-time">{timeText(e.timestamp)}</span><b>{labelEvent(e)}</b><small>{JSON.stringify(e.details||{})}</small></div>)}</div>
    </>;
  }
  function renderActivity() {
    return <>{header("Live Activity","Chronological backend/operator event feed")}<div className="panel"><div className="panel-title"><h2>Recent Events</h2><button className="btn small secondary" onClick={refreshAll}>Refresh</button></div>{displayEvents.length===0?<div className="empty-state">No events received. Activity will appear when backend control actions generate events. This is not yet a full strategy decision log.</div>:displayEvents.map((e,i)=><div className="event-row full" key={i}><span className="event-time">{timeText(e.timestamp)}</span><b>{labelEvent(e)}</b><small>{JSON.stringify(e.details||{})}</small></div>)}</div><div className="notice">Important: this feed currently shows operator-control events. The autonomous decision engine is not integrated and therefore does not yet emit complete strategy decision traces.</div></>;
  }
  function renderPositions() {
    return <>{header("Positions & Trades","Simulated positions, management parameters and trade history")}<div className="panel"><div className="panel-title"><h2>Open Paper Positions</h2><button className="btn small secondary" onClick={refreshAll}>Refresh</button></div>{openPositions.length===0?<div className="empty-state">No open paper positions.</div>:openPositions.map(p=><div className="position-card" key={p.position_id||p.symbol}><div className="position-head"><b>{p.symbol}</b><span className={"side-pill "+p.side}>{String(p.side).toUpperCase()}</span></div><div className="position-grid"><span>Entry<b>{value(p.entry_price)}</b></span><span>Mark<b>{value(p.mark_price)}</b></span><span>Quantity<b>{value(p.quantity)}</b></span><span>Leverage<b>{value(p.leverage)}x</b></span><span>SL<b>{value(p.stop_loss_price)}</b></span><span>TP<b>{value(p.take_profit_price)}</b></span><span>Trailing SL<b>{value(p.tsl_price)}</b></span><span>Trailing TP<b>{value(p.ttp_price)}</b></span></div><div className="list-row"><b>Unrealized P&L</b><b className={Number(p.unrealized_pnl)>=0?"positive":"negative"}>{money(p.unrealized_pnl)}</b></div></div>)}</div><div className="panel"><h2>Closed Trade History</h2>{closed.length===0?<div className="empty-state">No closed trades recorded.</div>:closed.slice().reverse().map((t,i)=><div className="list-row" key={t.trade_id||i}><div><b>{t.symbol} · {String(t.side).toUpperCase()}</b><small>{t.close_reason} · {timeText(t.closed_at_ms)}</small></div><div className="align-right"><b className={Number(t.net_pnl)>=0?"positive":"negative"}>{money(t.net_pnl)}</b><small>Exit {value(t.exit_price)}</small></div></div>)}</div></>;
  }
  function renderWatchlist() {
    const list=control?.watchlist||[];
    return <>{header("Watchlist","Symbols the operator has added to the control list")}<div className="panel"><div className="panel-title"><h2>Tracked Symbols</h2><span className="subtle">{list.length} listed</span></div><div className="add-symbol"><input placeholder="Enter symbol e.g. XRPUSDT" value={symbolInput} onChange={e=>setSymbolInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&addCoin()}/><button className="btn primary" onClick={addCoin} disabled={busy||!connected}>Add Symbol</button></div>{list.length===0?<div className="empty-state">Watchlist empty.</div>:list.map(s=><div className="list-row" key={s}><div><b>{s}</b><small>Operator watchlist · does not authorize a trade</small></div><button className="btn danger-outline small" onClick={()=>removeCoin(s)} disabled={busy||!connected}>Remove</button></div>)}</div><div className="notice">Watchlist changes currently update the backend control service's in-memory list. Scanner/strategy integration and persistence are not yet connected.</div></>;
  }
  function renderControls() {
    const cfg=control?.config||configDraft;
    return <>{header("Controls & Settings","Operator decisions sent to and validated by the backend")}
      <div className="panel connection-panel"><h2>Backend Connection</h2><label>Backend API URL<input placeholder="https://your-backend-host" value={apiBase} onChange={e=>setApiBase(e.target.value)}/></label><label>Control API token<input type="password" placeholder="Backend CONTROL_API_TOKEN" value={token} onChange={e=>setToken(e.target.value)}/></label><div className="control-buttons"><button className="btn primary" onClick={refreshAll}>Test / Refresh Connection</button></div><p className="subtle">Token is saved in this browser's local storage. Configure CONTROL_API_TOKEN on your backend before using controls.</p></div>
      <div className="panel"><div className="panel-title"><h2>Engine State</h2><span className="status-chip">{engineLabel}</span></div><p className="notice warning">Autonomous engine is not integrated yet. Start is blocked; these controls currently manage API control state only.</p><div className="control-buttons"><button className="btn primary" onClick={()=>command("START")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Start</button><button className="btn warn" onClick={()=>command("PAUSE")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Pause New Entries</button><button className="btn secondary" onClick={()=>command("RESUME")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Resume</button><button className="btn danger" onClick={()=>command("STOP")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Stop</button><button className="btn danger-outline" onClick={()=>command("EMERGENCY_HALT")} disabled={busy||!connected||!control?.autonomous_engine_integrated}>Emergency Halt</button></div></div>
      <div className="panel"><div className="panel-title"><h2>Trading Preferences</h2><span className="subtle">Saved to backend configuration only</span></div><div className="settings-grid"><label>Trading Direction<select value={cfg.trading_direction||"BOTH"} onChange={e=>setConfigDraft(prev=>({...prev,trading_direction:e.target.value}))}><option value="BOTH">Long & Short</option><option value="LONG">Long Only</option><option value="SHORT">Short Only</option></select></label><label>Entry Mode<select value={cfg.entry_mode||"AUTONOMOUS_PAPER"} onChange={e=>setConfigDraft(prev=>({...prev,entry_mode:e.target.value}))}><option value="AUTONOMOUS_PAPER">Autonomous Paper</option><option value="MANUAL_APPROVAL">Manual Approval</option></select></label></div><div className="toggle-grid"><label className="toggle-row"><span>Market regime filter</span><input type="checkbox" checked={Boolean(cfg.market_regime_filter_enabled)} onChange={e=>setConfigDraft(prev=>({...prev,market_regime_filter_enabled:e.target.checked}))}/></label></div><h3 className="subsection-title">Strategy Enable / Disable</h3><div className="toggle-grid">{Object.entries(cfg.strategy_enabled||{}).map(([key,on])=><label className="toggle-row" key={key}><span>{key.replaceAll("_"," ")}</span><input type="checkbox" checked={Boolean(on)} onChange={e=>setConfigDraft(prev=>({...prev,strategy_enabled:{...(prev.strategy_enabled||cfg.strategy_enabled),[key]:e.target.checked}}))}/></label>)}</div><p className="subtle">Strategy switches are recorded in backend memory; they do not currently turn strategy modules on/off.</p></div>
      <div className="panel"><div className="panel-title"><h2>Risk & Position Limits</h2><span className="subtle">Range-validated by backend</span></div><div className="settings-grid">{CONFIG_FIELDS.map(([key,label,min,max,step])=><label key={key}>{label}<input type="number" min={min} max={max} step={step} value={cfg[key]??""} onChange={e=>setConfigDraft(prev=>({...prev,[key]:Number(e.target.value)}))}/></label>)}</div><div className="toggle-grid">{["trailing_stop_enabled","trailing_take_profit_enabled","break_even_enabled"].map(k=><label className="toggle-row" key={k}><span>{k.replaceAll("_"," ")}</span><input type="checkbox" checked={Boolean(cfg[k])} onChange={e=>setConfigDraft(prev=>({...prev,[k]:e.target.checked}))}/></label>)}</div><button className="btn primary wide" onClick={saveConfig} disabled={busy||!connected}>Save Risk & Management Settings</button><p className="subtle">Currently applied in backend process memory only. These values are not yet wired into the autonomous strategy engine and are not durable across backend restarts.</p></div>
      <div className="panel"><h2>Exchange Data Sources</h2>{exchanges?Object.entries(exchanges).map(([name,status])=><div className="list-row" key={name}><b>{name}</b><span className="status-chip">{typeof status==="object"?status.status||status.connected?"CONNECTED":"UNKNOWN":String(status)}</span></div>):<div className="empty-state">Exchange status unavailable.</div>}<p className="subtle">Exchange feed enable/disable controls are not available in the current backend manager.</p></div>
      <div className="panel"><h2>Runtime Diagnostics</h2><pre className="diagnostic">{JSON.stringify({health,diagnostics,control},null,2)}</pre></div>
    </>;
  }

  const pages={dashboard:renderDashboard,activity:renderActivity,positions:renderPositions,watchlist:renderWatchlist,controls:renderControls};
  return <div className="app-root"><aside className="desktop-nav"><div className="brand-mark">OF</div><div className="brand-text">ORDERFLOW<span>SCALPER</span></div><nav>{NAV.map(n=><button key={n.key} className={page===n.key?"selected":""} onClick={()=>setPage(n.key)}><span className="nav-symbol">{n.icon}</span>{n.label}</button>)}</nav><div className="nav-foot"><span className={connected?"dot green":"dot red"}/>{connected?"API reachable":"API offline"}<small>Remote operator console</small></div></aside><main className="main"><div className="mobile-top"><div className="brand-mark small-mark">OF</div><div className="brand-text">ORDERFLOW<span>SCALPER</span></div><button className="refresh" onClick={refreshAll}>↻</button></div><div className="page-content">{pages[page]()}</div><footer className="footnote">OrderFlow Scalper · Remote Operator Console · Paper trading only</footer></main><nav className="mobile-nav">{NAV.map(n=><button key={n.key} className={page===n.key?"selected":""} onClick={()=>setPage(n.key)}><span>{n.icon}</span><small>{n.label.split(" ")[0]}</small></button>)}</nav>{notice&&<div className="toast" onClick={()=>setNotice("")}>{notice}<span>×</span></div>}</div>;
}
