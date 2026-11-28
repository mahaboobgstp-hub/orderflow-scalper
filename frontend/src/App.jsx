import { useEffect, useMemo, useState } from "react";
import { getMessageFeedState, getUnifiedFeedMessageState, getPrimaryBookState, getPrimaryBookDisplayLabel, getUnifiedBookState, normalizeFeedMonitorPayload } from "./feedFreshness.js";

const NAV = [
  { key: "dashboard", label: "Dashboard", icon: "⌂" },
  { key: "marketdata", label: "Feed Monitor", icon: "⌁" },
  { key: "testcenter", label: "Test Center", icon: "▣" },
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
  const [marketObs, setMarketObs] = useState(null);
  const [diagnostics, setDiagnostics] = useState(null);
  const [exchanges, setExchanges] = useState(null);
  const [paper, setPaper] = useState(null);
  const [history, setHistory] = useState(null);
  const [testSession, setTestSession] = useState(null);
  const [testOrders, setTestOrders] = useState(null);
  const [decisionStatus, setDecisionStatus] = useState(null);
  const [persistenceStatus, setPersistenceStatus] = useState(null);
  const [riskStatus, setRiskStatus] = useState(null);
  const [control, setControl] = useState(null);
  const [events, setEvents] = useState([]);
  const [scanner, setScanner] = useState(null);
  const [phaseCScanner, setPhaseCScanner] = useState(null);
  const [configDraft, setConfigDraft] = useState({});
  const [symbolInput, setSymbolInput] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [activityFilter, setActivityFilter] = useState("ALL");
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
    const [h,d,x,p,controlStatus,controlLog,tradeHistory,monitorLog,validation,orders,decision,persist,risk,feed] = await Promise.allSettled([
      api("/health"), api("/api/monitoring/diagnostics"), api("/api/exchanges/status"),
      api("/api/paper/account"), api("/api/control/status"), api("/api/control/events"),
      api("/api/paper/history?limit=50"), api("/api/monitoring/events?limit=100"),
      api("/api/paper/validation/status"), api("/api/paper/orders"), api("/api/decision-engine/status"), api("/api/paper/persistence/status"), api("/api/risk/status"), api("/api/market-data/observability")
    ]);
    if (h.status === "fulfilled") { setHealth(h.value); setConnected(true); } else { setHealth(null); setConnected(false); }
    setDiagnostics(d.status==="fulfilled" ? d.value : null);
    setExchanges(x.status==="fulfilled" ? x.value : null);
    setPaper(p.status==="fulfilled" ? p.value : null);
    if (controlStatus.status==="fulfilled") { setControl(controlStatus.value); setConfigDraft(prev => Object.keys(prev).length ? prev : (controlStatus.value.config || {})); }
    const controlEvents=controlLog.status==="fulfilled" ? controlLog.value.events || [] : [];
    const monitoringEvents=monitorLog.status==="fulfilled" ? (monitorLog.value.events || []).filter(evt=>evt.event!=="http_request") : [];
    setEvents([...controlEvents,...monitoringEvents].sort((a,b)=>(b.timestamp||0)-(a.timestamp||0)).slice(0,100));
    setHistory(tradeHistory.status==="fulfilled" ? tradeHistory.value : null);
    setTestSession(validation.status==="fulfilled" ? validation.value : null);
    setTestOrders(orders.status==="fulfilled" ? orders.value : null);
    setDecisionStatus(decision.status==="fulfilled" ? decision.value : null);
    setPersistenceStatus(persist.status==="fulfilled" ? persist.value : null);
    setRiskStatus(risk.status==="fulfilled" ? risk.value : null);
    setMarketObs(feed.status==="fulfilled" ? feed.value : null);
  }

  async function refreshScanner() {
    if (!base) return;
    try { const result = await api("/api/scanner/coins?limit=15&include_rejected=false"); setScanner(result); }
    catch { setScanner(null); }
  }

  async function refreshPhaseCScanner() {
    if (!base) return;
    try { setPhaseCScanner(await api("/api/scanner/opportunities?limit=12&min_score=0&min_volume_usdt=5000000&max_spread_pct=0.12&include_filtered=false")); }
    catch { setPhaseCScanner(null); }
  }

  useEffect(() => {
    localStorage.setItem("ofs_api", apiBase);
    localStorage.setItem("ofs_token", token);
    refreshAll();
    refreshScanner();
    refreshPhaseCScanner();
    const timer = setInterval(refreshAll, 10000);
    const scanTimer = setInterval(refreshScanner, 45000);
    const phaseCTimer = setInterval(refreshPhaseCScanner, 45000);
    return () => { clearInterval(timer); clearInterval(scanTimer); clearInterval(phaseCTimer); };
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
  async function validationCommand(action) {
    setBusy(true); setNotice("");
    const endpoint={START:"/api/paper/validation/start",PAUSE:"/api/paper/validation/pause",RESUME:"/api/paper/validation/resume",STOP:"/api/paper/validation/stop"}[action];
    try { const result=await api(endpoint,{method:"POST"}); setTestSession(result); setNotice("Paper validation session: "+(result.state||action)); await refreshAll(); }
    catch(e){setNotice(e.message)} finally {setBusy(false)}
  }
  function renderTestCenter() {
    const decisions=decisionStatus?.runtime?.recent_decisions || [];
    const last=decisions.length ? decisions[decisions.length-1] : null;
    const orderList=testOrders?.orders || testOrders?.data?.orders || [];
    const sessionEvents=testSession?.events || [];
    const layerEntries=last?.layers ? Object.entries(last.layers) : [];
    const fmtDate=(v)=>v ? new Date(v).toLocaleString() : "--";
    return <>
      {header("Test Center","Observe actual paper-session events, orders, decisions, risk and recovery data")}
      <div className="status-strip"><span className="status-chip paper">PAPER ONLY</span><span className="status-chip">{testSession?.state || "SESSION STATUS UNAVAILABLE"}</span><span className="subtle">No live exchange orders are possible from this console.</span></div>
      <div className="stats-grid">
        {stat("Validation Session",testSession?.state || "Unavailable","Controller status")}
        {stat("Trades Started",testSession?.trades_started ?? "--","Session entry count")}
        {stat("Closed Session Trades",testSession?.closed_trades ?? "--","Session tracked exits")}
        {stat("Session Realized P&L",money(testSession?.realized_pnl),"Controller-reported value")}
      </div>
      <div className="panel"><div className="panel-title"><h2>Controlled Paper Session</h2><span className="subtle">Session controls only</span></div>
        <div className="control-buttons">
          <button className="btn primary" onClick={()=>validationCommand("START")} disabled={busy||!connected||testSession?.state==="ACTIVE"}>Start Session</button>
          <button className="btn warn" onClick={()=>validationCommand("PAUSE")} disabled={busy||testSession?.state!=="ACTIVE"}>Pause</button>
          <button className="btn secondary" onClick={()=>validationCommand("RESUME")} disabled={busy||testSession?.state!=="PAUSED"}>Resume</button>
          <button className="btn danger" onClick={()=>validationCommand("STOP")} disabled={busy||!["ACTIVE","PAUSED"].includes(testSession?.state)}>Stop Session</button>
          <button className="btn secondary" onClick={refreshAll} disabled={busy}>Refresh Evidence</button>
        </div>
        <div className="notice warning">Starting a session enables the controlled paper-validation runtime. This is not live trading. Do not start until we explicitly begin the test phase.</div>
        <div className="diagnostic">{JSON.stringify(testSession?.config || {},null,2)}</div>
      </div>
      <div className="split-grid">
        <div className="panel"><h2>Actual Simulated Orders</h2><p className="subtle">Read-only records returned by the paper simulator</p>
          {!testOrders ? <div className="empty-state">Order records unavailable or API not connected.</div> : orderList.length===0 ? <div className="empty-state">No simulator orders recorded.</div> : orderList.slice().reverse().map((o,i)=><div className="list-row" key={o.order_id||i}><div><b>{o.symbol} · {String(o.side||"").toUpperCase()}</b><small>{o.status} · {fmtDate(o.created_at_ms)}</small></div><div className="align-right"><b>{value(o.quantity)}</b><small>Entry {value(o.entry_price)} · {o.leverage}x</small></div></div>)}
        </div>
        <div className="panel"><h2>Paper Account Snapshot</h2>{paper ? <pre className="diagnostic">{JSON.stringify({cash_balance:paper.cash_balance,equity:paper.equity,realized_pnl:paper.realized_pnl,unrealized_pnl:paper.unrealized_pnl,open_position_count:paper.open_position_count},null,2)}</pre> : <div className="empty-state">Account snapshot unavailable.</div>}</div>
      </div>
      <div className="panel"><div className="panel-title"><h2>Nine-Layer Decision Trace</h2><span className="subtle">Latest runtime decision, if available</span></div>
        {!last ? <div className="empty-state">No recent decision trace returned by runtime yet.</div> : <><div className="list-row"><b>{last.symbol} · {last.decision}</b><span className="status-chip">{last.score ?? "--"} score</span></div><div className="layer-grid">{layerEntries.map(([key,l])=><div className="layer-card" key={key}><b>{key.replaceAll("_"," ")}</b><span className="status-chip">{l.direction||"N/A"}</span><small>Score: {l.score??"--"} · Confidence: {l.confidence??"--"}</small><p>{(l.reasons||[]).join(" | ")||"No reason detail"}</p></div>)}</div><pre className="diagnostic">{JSON.stringify(last,null,2)}</pre></>}
      </div>
      <div className="split-grid">
        <div className="panel"><h2>Risk Monitor</h2>{riskStatus?<pre className="diagnostic">{JSON.stringify(riskStatus,null,2)}</pre>:<div className="empty-state">Risk status unavailable.</div>}</div>
        <div className="panel"><h2>Persistence & Recovery</h2>{persistenceStatus?<pre className="diagnostic">{JSON.stringify(persistenceStatus,null,2)}</pre>:<div className="empty-state">Persistence diagnostics unavailable.</div>}</div>
      </div>
      <div className="panel"><h2>Session Event Timeline</h2>{sessionEvents.length===0?<div className="empty-state">No controlled-session events reported yet.</div>:sessionEvents.slice().reverse().map((e,i)=><div className="event-row full" key={i}><span className="event-time">{e.at?fmtDate(e.at):"--"}</span><b>{e.event||"Session event"}</b><small>{JSON.stringify(e.data||{})}</small></div>)}</div>
    </>;
  }
  function renderMarketData() {
    const {payload,summary,unified,adapterList,books,exchangeStats,feeds,primary}=normalizeFeedMonitorPayload(marketObs);
    const primaryBookState=getPrimaryBookState(primary);
    const primaryBookFresh=primaryBookState==="HEALTHY"||primaryBookState==="FRESH (LEGACY)";
    const messageState=(x)=>getMessageFeedState(x,unified.stale_after_seconds);
    return <>{header("Live Market & Feed Monitor","Read-only diagnostics: feed connectivity, freshness, book sync and integrity")}
      <div className="stats-grid">
        {stat("Fresh Message Feeds",summary.fresh_message_feed_count??summary.healthy_feed_count??0,"Enabled/connected feeds with recent messages")}
        {stat("Healthy Feeds",summary.healthy_feed_count??0,"Fresh synchronized book per feed")}
        {stat("Synchronized Books",summary.synchronized_book_count??0,"Fresh synchronized books")}
        {stat("Unified Books",summary.unified_book_count??0,"Book entries currently tracked")}
        {stat("Feed Errors",summary.feed_errors??0,"Adapters reporting errors")}
      </div>
      <div className="panel"><div className="panel-title"><h2>Safety & Runtime Boundary</h2><button className="btn small secondary" onClick={refreshAll}>Refresh</button></div>
        <div className="list-row"><b>Market data mode</b><span>{payload.mode||"Unknown"}</span></div>
        <div className="list-row"><b>Real exchange execution</b><span className="negative">Disabled</span></div>
        <div className="list-row"><b>Primary Binance demo book</b><span>{getPrimaryBookDisplayLabel(primaryBookState)}</span></div>
        <div className="list-row"><b>Binance demo last update ID</b><span>{value(payload.primary_binance_demo_stream?.last_update_id)}</span></div>
        <div className="list-row"><b>Primary book freshness</b><span className={"status-chip "+(primaryBookFresh?"good":"bad")}>{primaryBookState}</span></div>
        <div className="list-row"><b>Last depth message age</b><span>{primary.last_event_age_seconds==null?"--":primary.last_event_age_seconds+"s"}</span></div>
        <div className="list-row"><b>Applied book update age</b><span className={"status-chip "+(primaryBookFresh?"good":"bad")}>{primary.last_book_update_age_seconds==null?"--":primary.last_book_update_age_seconds+"s"}</span></div>
        <div className="list-row"><b>Connected for</b><span>{primary.connected_duration_seconds==null?"--":primary.connected_duration_seconds+"s"}</span></div>
        <div className="list-row"><b>Synchronized for</b><span>{primary.synchronized_duration_seconds==null?"--":primary.synchronized_duration_seconds+"s"}</span></div>
        <div className="list-row"><b>Connection attempts / successes</b><span>{primary.connection_attempt_count??0} / {primary.successful_connection_count??0}</span></div>
        <div className="list-row"><b>Reconnects / recoveries</b><span>{primary.reconnect_count??0} / {primary.recovery_count??0}</span></div>
        <div className="list-row"><b>Last recovery</b><span>{primary.last_recovery_age_seconds==null?"Never":primary.last_recovery_age_seconds+"s ago"}</span></div>
        <div className="list-row"><b>REST snapshots loaded</b><span>{primary.snapshot_count??0}</span></div>
        <div className="list-row"><b>Snapshot depth cap</b><span>{primary.snapshot_limit??"--"} levels/side</span></div>
        <div className="list-row"><b>Last disconnect reason</b><span>{primary.last_disconnect_reason||"None recorded"}</span></div>
        <div className="list-row"><b>Sequence gaps</b><span className={payload.primary_binance_demo_stream?.sequence_gap_count?"negative":""}>{payload.primary_binance_demo_stream?.sequence_gap_count??0}</span></div>
        <div className="list-row"><b>Depth events received</b><span>{payload.primary_binance_demo_stream?.messages_received??0}</span></div>
        <div className="list-row"><b>Rejected depth messages</b><span>{value(primary.invalid_depth_message_count)}</span></div>
        <div className="list-row"><b>Depth buffer overflow recoveries</b><span className={primary.snapshot_buffer_overflow_count?"negative":""}>{primary.snapshot_buffer_overflow_count??0}</span></div>
        <div className="list-row"><b>Primary stream error</b><span>{payload.primary_binance_demo_stream?.last_error||"None reported"}</span></div>
        <div className="list-row"><b>Safety</b><span>{payload.summary?.safety||"PUBLIC FEEDS ONLY"}</span></div>
      </div>
      <div className="panel"><div className="panel-title"><h2>Exchange Feed Connections</h2></div>
        {adapterList.length===0?<div className="empty-state">No exchange feed diagnostics available. Connect to backend and refresh.</div>:adapterList.map(x=>{
          const state=messageState(x);
          const stateClass=state==="FRESH"?"paper":["STALE","DISCONNECTED"].includes(state)?"bad":"";
          return <div className="event-row full" key={x.exchange}>
          <b>{String(x.exchange||"Exchange").toUpperCase()}</b><span className={"status-chip "+stateClass}>{state}</span>
          <small>Enabled {String(x.enabled)} · Symbol {x.symbol} · Message age {x.last_message_age_seconds==null?"--":x.last_message_age_seconds+"s"} · Reconnects {x.reconnect_count??0}</small>
          <small>Error: {x.last_error||"None"}</small>
        </div>;
        })}
      </div>
      <div className="panel"><div className="panel-title"><h2>Unified Order Books</h2></div>
        {Object.keys(books).length===0?<div className="empty-state">No normalized books received yet. This is a live status, not simulated sample data.</div>:Object.entries(books).map(([key,b])=>{
          const bookState=getUnifiedBookState(b,unified.stale_after_seconds);
          const statusLabel=bookState==="HEALTHY"?"SYNCED & FRESH":bookState;
          const statusClass="status-chip "+(bookState==="HEALTHY"?"paper":bookState==="STALE"||bookState==="UNHEALTHY"?"bad":"");
          return <div className="decision-card" key={key}>
          <div className="decision-head"><b>{key}</b><span className={statusClass}>{statusLabel}</span></div>
          <div className="decision-metrics"><span>Sequence <b>{value(b.sequence)}</b></span><span>Age <b>{b.age_seconds==null?"--":b.age_seconds+"s"}</b></span><span>Spread <b>{b.spread==null?"--":b.spread}</b></span><span>Top-10 Imbalance <b>{b.imbalance_top10==null?"--":(b.imbalance_top10*100).toFixed(1)+"%"}</b></span></div>
          <div className="decision-metrics"><span>Best Bid <b>{value(b.best_bid)}</b></span><span>Best Ask <b>{value(b.best_ask)}</b></span><span>Bid Depth <b>{b.bid_depth_top10??"--"}</b></span><span>Ask Depth <b>{b.ask_depth_top10??"--"}</b></span></div>
          <div className="decision-outcome">Integrity: {b.integrity_error||"No error reported"}</div>
        </div>;
        })}
      </div>
      <div className="panel"><div className="panel-title"><h2>Per-Symbol Message Freshness</h2></div>
        {Object.keys(feeds).length===0?<div className="empty-state">No per-symbol message activity has been recorded.</div>:Object.entries(feeds).map(([key,feed])=>{
          const state=getUnifiedFeedMessageState(feed,unified.stale_after_seconds);
          const stateClass=state==="FRESH"?"paper":state==="STALE"?"bad":"";
          return <div className="list-row" key={key}><div><b>{key}</b><small>Messages {feed.messages_received??0} · Last message {feed.last_message_age_seconds==null?"--":feed.last_message_age_seconds+"s ago"}</small></div><span className={"status-chip "+stateClass}>{state}</span></div>;
        })}
        <p className="subtle">Message activity is tracked separately for each exchange-symbol pair; trade messages do not refresh book freshness.</p>
      </div>
      <div className="panel"><h2>Exchange Message Activity</h2>{Object.entries(exchangeStats).length===0?<div className="empty-state">No unified exchange messages recorded.</div>:Object.entries(unified.exchanges).map(([name,stats])=><div className="list-row" key={name}><b>{name.toUpperCase()}</b><span>Messages {stats.messages_received} · Last seen {stats.last_message_age_seconds==null?"--":stats.last_message_age_seconds+"s ago"}</span></div>)}
        <p className="subtle">This page refreshes with the existing polling cadence. Counts and timestamps are taken from backend diagnostics.</p>
      </div>
    </>;
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
      <div className="panel"><div className="panel-title"><h2>Phase C · Ranked Opportunities</h2><button className="link-button" onClick={refreshPhaseCScanner}>Refresh ranking</button></div><div className="subtle">Read-only heuristic score · public market scan · not a trade signal. Ranking excludes scanner-filtered markets by default.</div>{!phaseCScanner?<div className="empty-state">Phase C scan unavailable. API endpoint may not yet be deployed.</div>:phaseCScanner.markets?.length===0?<div className="empty-state">No ranked candidates meet the selected quality filters.</div>:phaseCScanner.markets.slice(0,8).map((coin,i)=><div className="list-row" key={coin.symbol||i}><div><b>#{coin.phase_c_rank} · {coin.symbol}</b><small>Score breakdown: Vol {coin.phase_c_score_components?.volume??"--"} · Spread {coin.phase_c_score_components?.spread??"--"} · Range {coin.phase_c_score_components?.range??"--"} · Activity {coin.phase_c_score_components?.trade_activity??"--"} · Momentum {coin.phase_c_score_components?.momentum_proxy??"--"}</small><small>{(coin.phase_c_quality_flags||[]).join(" · ")||"No quality flags"}</small></div><div className="align-right"><b>{coin.phase_c_score}</b><small>Phase C score</small></div></div>)}</div>
      <div className="panel"><div className="panel-title"><h2>Recent Engine Events</h2><button className="link-button" onClick={()=>setPage("activity")}>View activity</button></div>{displayEvents.length===0?<div className="empty-state">No operator events yet.</div>:displayEvents.slice(0,8).map((e,i)=><div className="event-row" key={i}><span className="event-time">{timeText(e.timestamp)}</span><b>{labelEvent(e)}</b><small>{JSON.stringify(e.details||{})}</small></div>)}</div>
    </>;
  }
  function renderActivity() {
    const runtime=decisionStatus?.runtime || {};
    const decisions=[...(runtime.recent_decisions||[])].reverse();
    const filtered=activityFilter==="ALL" ? decisions : decisions.filter(d=>String(d.decision||"").toUpperCase()===activityFilter);
    const layerInfo={
      order_book_imbalance:["Order Book Imbalance","Bid vs ask depth pressure"],
      absorption:["Absorption","Aggressive flow versus price response"],
      liquidity_breakout:["Liquidity Breakout","Break or reclaim of liquidity zones"],
      aggressive_order_flow:["Aggressive Order Flow","Market-buy and market-sell activity"],
      momentum:["Momentum","Directional price and activity acceleration"],
      spread_liquidity:["Spread & Liquidity","Execution friction and available depth"],
      volatility_regime:["Volatility Regime","Volatility conditions and risk context"],
      broader_market_context:["Broader Market Context","BTC / market-wide directional context"],
      risk_execution:["Risk & Execution Gate","Risk limits and entry permission"],
    };
    const decisionLayers=(d)=>Object.keys(layerInfo).map((key)=>[key,(d.layers||{})[key]||{direction:"N/A",score:null,confidence:null,available:false,reasons:[],data:{},_missing:true}]);
    const layerSummary=(d)=>{
      const ls=decisionLayers(d).map((entry)=>entry[1]);
      return {available:ls.filter((l)=>l.available).length,unavailable:ls.filter((l)=>!l.available&&!l._missing).length,
        missing:ls.filter((l)=>l._missing).length,
        buy:ls.filter((l)=>l.available&&l.direction==="BUY").length,sell:ls.filter((l)=>l.available&&l.direction==="SELL").length,
        neutral:ls.filter((l)=>l.available&&l.direction==="NEUTRAL").length,block:ls.filter((l)=>l.direction==="BLOCK").length};
    };
    const decisionTime=runtime.last_scan_time ? timeText(runtime.last_scan_time) : "Last scan time unavailable";
    return <>
      {header("Live Activity","Live nine-layer decisions, paper execution outcomes and backend events")}
      <div className="stats-grid">
        {stat("Runtime State",runtime.state||"Unavailable","Autonomous paper runtime")}
        {stat("Decision Count",runtime.decision_count??"--","Runtime decision records")}
        {stat("Last Scan",decisionTime,"Latest scan timestamp")}
        {stat("Mode",runtime.mode||"PAPER_ONLY","Exchange orders disabled")}
      </div>
      <div className="panel">
        <div className="panel-title"><h2>Recent Nine-Layer Decisions</h2><button className="btn small secondary" onClick={refreshAll}>Refresh</button></div>
        <div className="control-buttons">
          <label>Filter decisions <select value={activityFilter} onChange={e=>setActivityFilter(e.target.value)}><option value="ALL">All</option><option value="BUY">BUY</option><option value="SELL">SELL</option><option value="HOLD">HOLD</option><option value="REJECT">REJECT</option></select></label>
          <span className="subtle">Auto-refreshes with backend polling · displayed decisions are real backend responses, not sample data.</span>
        </div>
        {!connected ? <div className="empty-state">Connect to the backend to load decision traces.</div> : filtered.length===0 ? <div className="empty-state">No decisions for this filter yet. The engine may be stopped, scanning may be unavailable, or the current scan produced no records.</div> : filtered.map((d,i)=><div className="decision-card" key={d.symbol+"-"+i}>
          <div className="decision-head"><div><b>{d.symbol||"Unknown symbol"}</b><small>{timeText(d.evaluated_at||runtime.last_scan_time)} · Exchange {d.exchange||"--"} · Paper only</small></div><span className={"status-chip "+(["BUY","SELL"].includes(String(d.decision).toUpperCase())?"paper":"")}>{String(d.decision||"UNKNOWN").toUpperCase()}</span></div>
          <div className="decision-metrics"><span>Score <b>{value(d.score)}</b></span><span>Consensus <b>{d.consensus_ratio==null?"--":(Number(d.consensus_ratio)*100).toFixed(1)+"%"}</b></span><span>Directional layers <b>{d.directional_layers_available??"--"}/{d.minimum_layers_required??"--"} min</b></span><span>Decision eligible <b>{typeof d.entry_eligible==="boolean"?(d.entry_eligible?"YES":"NO"):"UNKNOWN"}</b></span><span>Session gate <b>{d.controlled_session_gate?.allowed===true?"PASS":d.controlled_session_gate?.allowed===false?"BLOCKED":"NOT REPORTED"}</b></span></div>
          <div className="layer-summary"><span>Available <b>{layerSummary(d).available}/9</b></span><span>Unavailable <b>{layerSummary(d).unavailable}</b></span><span>Missing <b>{layerSummary(d).missing}</b></span><span>BUY <b>{layerSummary(d).buy}</b></span><span>SELL <b>{layerSummary(d).sell}</b></span><span>Neutral <b>{layerSummary(d).neutral}</b></span><span>Blocks <b>{layerSummary(d).block}</b></span></div><div className="layer-grid">{decisionLayers(d).map(([key,l])=><div className="layer-card" key={key}><b>{layerInfo[key]?.[0]||key.replaceAll("_"," ")}</b><small className="layer-purpose">{layerInfo[key]?.[1]||"Decision evidence"}</small><span className={"status-chip "+(l.direction==="BUY"?"paper":l.direction==="SELL"?"negative":"")}>{l._missing?"MISSING":l.direction||"N/A"}</span><small>Score <strong>{l.score??"--"}</strong> · Confidence <strong>{l.confidence??"--"}</strong> · {l._missing?"Missing output":l.available?"Available":"Unavailable"}</small>{l.score!=null&&<div className="layer-score-track"><div className={"layer-score-fill "+(Number(l.score)>=0?"buy":"sell")} style={{width:(Math.min(100,Math.abs(Number(l.score))))+"%"}}/></div>}<p>{l._missing?"Layer output missing from backend decision record":(l.reasons||[]).join(" · ")||"No explanation supplied"}</p>{l.data&&Object.keys(l.data).length>0&&<details><summary>Layer data</summary><pre className="diagnostic">{JSON.stringify(l.data,null,2)}</pre></details>}</div>)}</div>
          <div className="decision-outcome"><b>Controlled session gate:</b> {d.controlled_session_gate?.allowed===true?"PASS":d.controlled_session_gate?.allowed===false?"BLOCKED":"NOT REPORTED"}{d.controlled_session_gate?.session_state?" · Session: "+d.controlled_session_gate.session_state:""}{Array.isArray(d.controlled_session_gate?.blockers)&&d.controlled_session_gate.blockers.length?" · Blockers: "+d.controlled_session_gate.blockers.join(", "):""}</div><div className="decision-outcome"><b>Backend records:</b> Decision {d.decision_persistence?.status||"NOT REPORTED"}{d.decision_persistence?.record_id?" · ID "+d.decision_persistence.record_id:""} · Signal {d.signal_persistence?.status||"NOT REPORTED"}{d.signal_persistence?.record_id?" · ID "+d.signal_persistence.record_id:""}</div><div className="decision-outcome"><b>Paper execution:</b> {d.paper_execution?.status||"Not reported"}{d.paper_execution?.reason? " — "+d.paper_execution.reason:""}{d.paper_execution?.session_blockers?.length? " · Blockers: "+d.paper_execution.session_blockers.join(", "):""}</div>
          <details><summary>Full decision data</summary><pre className="diagnostic">{JSON.stringify(d,null,2)}</pre></details>
        </div>)}
      </div>
      <div className="panel"><div className="panel-title"><h2>Backend / Operator Events</h2><button className="btn small secondary" onClick={refreshAll}>Refresh</button></div>{displayEvents.length===0?<div className="empty-state">No events recorded.</div>:displayEvents.map((e,i)=><div className="event-row full" key={i}><span className="event-time">{timeText(e.timestamp)}</span><b>{labelEvent(e)}</b><small>{JSON.stringify(e.details||{})}</small></div>)}</div>
      <div className="notice">Decision records are sourced from the runtime's recent in-memory decision list. They are not yet a durable, searchable decision-history archive; the timestamp shown is the latest scan timestamp shared by this batch.</div>
    </>;
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
      <div className="panel"><h2>Exchange Data Sources</h2>{exchanges?Object.entries(exchanges).map(([name,status])=><div className="list-row" key={name}><b>{name}</b><span className="status-chip">{typeof status==="object"?status.status||status.connected?"CONNECTED":"UNKNOWN":String(status)}</span></div>):<div className="empty-state">Exchange status unavailable.</div>}<div className="toggle-grid">{["binance","bybit","delta"].map(name=><label className="toggle-row" key={name}><span>{name.toUpperCase()} feed preference</span><input type="checkbox" checked={Boolean(cfg.exchange_enabled?.[name])} onChange={e=>setConfigDraft(prev=>({...prev,exchange_enabled:{...(prev.exchange_enabled||cfg.exchange_enabled),[name]:e.target.checked}}))}/></label>)}</div><p className="subtle">Feed preferences are recorded only; the live exchange manager does not yet apply these runtime toggles. Save them using the risk/settings save button.</p></div>
      <div className="panel"><h2>Runtime Diagnostics</h2><pre className="diagnostic">{JSON.stringify({health,diagnostics,control},null,2)}</pre></div>
    </>;
  }

  const pages={dashboard:renderDashboard,marketdata:renderMarketData,testcenter:renderTestCenter,activity:renderActivity,positions:renderPositions,watchlist:renderWatchlist,controls:renderControls};
  return <div className="app-root"><aside className="desktop-nav"><div className="brand-mark">OF</div><div className="brand-text">ORDERFLOW<span>SCALPER</span></div><nav>{NAV.map(n=><button key={n.key} className={page===n.key?"selected":""} onClick={()=>setPage(n.key)}><span className="nav-symbol">{n.icon}</span>{n.label}</button>)}</nav><div className="nav-foot"><span className={connected?"dot green":"dot red"}/>{connected?"API reachable":"API offline"}<small>Remote operator console</small></div></aside><main className="main"><div className="mobile-top"><div className="brand-mark small-mark">OF</div><div className="brand-text">ORDERFLOW<span>SCALPER</span></div><button className="refresh" onClick={refreshAll}>↻</button></div><div className="page-content">{pages[page]()}</div><footer className="footnote">OrderFlow Scalper · Remote Operator Console · Paper trading only</footer></main><nav className="mobile-nav">{NAV.map(n=><button key={n.key} className={page===n.key?"selected":""} onClick={()=>setPage(n.key)}><span>{n.icon}</span><small>{n.label.split(" ")[0]}</small></button>)}</nav>{notice&&<div className="toast" onClick={()=>setNotice("")}>{notice}<span>×</span></div>}</div>;
}
