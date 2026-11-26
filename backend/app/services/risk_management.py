"""Phase 10 risk controls and position-sizing calculator. No order execution."""
from __future__ import annotations
import math
from typing import Any

class RiskManagementEngine:
    def __init__(self, defaults: dict[str,Any] | None = None):
        self.defaults={
            "risk_per_trade_pct":0.5,
            "max_daily_loss_pct":2.0,
            "max_total_open_risk_pct":3.0,
            "max_position_notional_pct":25.0,
            "max_leverage":5.0,
            "max_positions":3,
            "max_consecutive_losses":3,
        }
        if defaults: self.defaults.update(defaults)

    @staticmethod
    def _finite(v):
        try:
            n=float(v)
            return n if math.isfinite(n) else None
        except (TypeError,ValueError): return None

    def status(self):
        return {"phase":10,"engine":"risk_management_position_sizing","mode":"calculation_only","order_execution":False,"default_limits":self.defaults.copy(),"notes":["Risk settings are conservative starter defaults, not personalized financial advice.","Risk calculation assumes stop-loss is executed at the specified stop price; gaps/slippage may increase realized loss."]}

    def calculate(self, request: dict[str,Any]) -> dict[str,Any]:
        equity=self._finite(request.get("account_equity")); entry=self._finite(request.get("entry_price")); stop=self._finite(request.get("stop_loss_price"))
        risk_pct=self._finite(request.get("risk_per_trade_pct")) or self.defaults["risk_per_trade_pct"]
        leverage=self._finite(request.get("leverage")) or 1.0
        max_notional_pct=self._finite(request.get("max_position_notional_pct")) or self.defaults["max_position_notional_pct"]
        if equity is None or equity<=0: raise ValueError("account_equity must be greater than zero.")
        if entry is None or entry<=0: raise ValueError("entry_price must be greater than zero.")
        if stop is None or stop<=0 or stop==entry: raise ValueError("stop_loss_price must be positive and different from entry.")
        side=str(request.get("side","")).lower()
        if side not in ("long","short"): raise ValueError("side must be long or short.")
        if side=="long" and stop>=entry: raise ValueError("For a long, stop loss must be below entry price.")
        if side=="short" and stop<=entry: raise ValueError("For a short, stop loss must be above entry price.")
        if not 0.01<=risk_pct<=5: raise ValueError("risk_per_trade_pct must be between 0.01 and 5.")
        if not 1<=leverage<=self.defaults["max_leverage"]: raise ValueError(f"leverage must be between 1 and {self.defaults['max_leverage']}.")
        if not 1<=max_notional_pct<=100: raise ValueError("max_position_notional_pct must be between 1 and 100.")
        risk_cash=equity*risk_pct/100; stop_distance=abs(entry-stop); stop_distance_pct=stop_distance/entry*100
        raw_qty=risk_cash/stop_distance
        cap_notional=equity*max_notional_pct/100
        cap_qty=cap_notional/entry
        quantity=min(raw_qty,cap_qty)
        notional=quantity*entry; margin=notional/leverage; estimated_loss=quantity*stop_distance
        cap_limited=quantity<raw_qty
        return {"engine":"phase10_risk_management","mode":"calculation_only","side":side,"symbol":str(request.get("symbol","UNKNOWN")).upper(),"account_equity":round(equity,8),"risk_per_trade_pct":risk_pct,"risk_budget":round(risk_cash,8),"entry_price":entry,"stop_loss_price":stop,"stop_distance":round(stop_distance,8),"stop_distance_pct":round(stop_distance_pct,6),"leverage":leverage,"position_quantity":round(quantity,12),"position_notional":round(notional,8),"estimated_initial_margin":round(margin,8),"estimated_loss_at_stop":round(estimated_loss,8),"estimated_loss_pct_of_equity":round(estimated_loss/equity*100,6),"notional_cap":round(cap_notional,8),"risk_cap_limited_quantity":round(raw_qty,12),"notional_cap_quantity":round(cap_qty,12),"position_limited_by_notional_cap":cap_limited,"assumptions":["Linear USDT-margined contract approximation; quantity is base-asset units.","Fees, funding, slippage, liquidation price, contract multipliers and exchange lot-size filters are not included.","Stop-loss is not guaranteed to fill at its trigger price.","Calculator does not submit orders."]}

    def evaluate_portfolio(self, account_equity: float, daily_realized_loss: float = 0.0, open_risk: float = 0.0, open_positions: int = 0, consecutive_losses: int = 0, risk_per_trade_pct: float | None = None) -> dict[str,Any]:
        eq=self._finite(account_equity)
        if eq is None or eq<=0: raise ValueError("account_equity must be positive.")
        daily=max(0.0,self._finite(daily_realized_loss) or 0.0); opened=max(0.0,self._finite(open_risk) or 0.0)
        positions=max(0,int(open_positions)); losses=max(0,int(consecutive_losses))
        trade_risk=self._finite(risk_per_trade_pct) if risk_per_trade_pct is not None else self.defaults["risk_per_trade_pct"]
        trade_risk=max(0.0,trade_risk or 0.0)
        daily_limit=eq*self.defaults["max_daily_loss_pct"]/100; open_limit=eq*self.defaults["max_total_open_risk_pct"]/100; next_risk=eq*trade_risk/100
        blockers=[]
        if daily>=daily_limit: blockers.append("DAILY_LOSS_LIMIT_REACHED")
        if opened+next_risk>open_limit: blockers.append("OPEN_RISK_LIMIT_WOULD_BE_EXCEEDED")
        if positions>=self.defaults["max_positions"]: blockers.append("MAX_OPEN_POSITIONS_REACHED")
        if losses>=self.defaults["max_consecutive_losses"]: blockers.append("CONSECUTIVE_LOSS_LIMIT_REACHED")
        return {"engine":"phase10_portfolio_risk_guard","mode":"advisory_guard_only","account_equity":eq,"daily_realized_loss":daily,"daily_loss_limit":round(daily_limit,8),"open_risk":opened,"open_risk_limit":round(open_limit,8),"proposed_trade_risk":round(next_risk,8),"open_positions":positions,"max_open_positions":self.defaults["max_positions"],"consecutive_losses":losses,"max_consecutive_losses":self.defaults["max_consecutive_losses"],"allowed_to_consider_new_trade":not blockers,"blockers":blockers,"warning":"Guard is advisory only and is not connected to execution."}
