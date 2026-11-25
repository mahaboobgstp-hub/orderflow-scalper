# OrderFlow Scalper Android Remote Shell

This branch contains the dedicated Android shell APK project.

## Architecture
- APK installed once; it opens the remotely hosted OrderFlow Scalper frontend.
- Frontend UI updates are delivered by web deployment, not APK reinstall.
- Android and browser share one backend trading engine.
- This branch contains shell/build configuration only. The web UI remains on `main`.

## Remote frontend
Configured in `frontend/capacitor.config.json` to load the current Vercel production URL.

## Build
GitHub Actions workflow `.github/workflows/android-shell-apk.yml` builds a debug APK on pushes to this branch or via manual workflow dispatch. Download the APK from the workflow run's Artifacts section.

## Limitations
- Requires network connectivity to the remote frontend.
- Native shell/security changes require a new APK build and installation.
- Frontend updates are remote; backend deployment remains separate.
- Control endpoints require a configured backend control token and currently report that autonomous engine integration is not implemented.
