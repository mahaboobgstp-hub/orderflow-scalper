# OrderFlow Scalper Operator Console

## Web frontend
The web application remains on `main`. It is being redesigned as a mobile-first remote operator console.

## Backend control API
The backend code adds `/api/control` routes. Set a strong secret on the backend host before accepting control actions:

```bash
export CONTROL_API_TOKEN='replace-with-a-long-random-secret'
export FRONTEND_ORIGINS='https://orderflow-scalper-ivory.vercel.app'
```

The frontend API URL must be set in Controls & Settings. The control token is stored in browser local storage for that client. Do not share it or commit it to the repository.

## Current implementation limitations
- Control configuration, watchlist, and event records are process-memory only and reset when the backend restarts.
- Autonomous strategy decision/execution loop is not integrated with the new operator controls. Engine commands intentionally return a conflict and are not applied.
- Strategy switches, scanner filters, trading direction, and risk settings are currently validated and recorded only; they are not yet consumed by the strategy engine.
- Watchlist changes are currently stored in the operator-control service only and do not yet alter the scanner's active universe.
- Existing paper-trading endpoints remain paper-only; this UI does not enable real order placement.
- Exchange status is informational; exchange runtime enable/disable commands are not implemented.
- The API currently has no user-account authentication. The control token protects mutating operator endpoints, but a production deployment should use TLS and a proper authentication/authorization layer before exposing it publicly.

## Android shell
The `android-remote-shell` branch contains the Capacitor wrapper. It loads the Vercel production domain remotely. Ordinary frontend changes should appear after web deployment without reinstalling the APK. Native shell changes still require a new APK.
