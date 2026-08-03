# ERPNext AI Desktop

Desktop wrapper for Windows and Linux that displays ERPNext with a selectable Claude.ai or ChatGPT side panel using independent Electron `WebContentsView` instances.

## Features

- Persistent, isolated ERPNext and Claude login sessions
- Selectable Claude or ChatGPT panel with a separate persistent login for each service
- Assistants load on demand with a standard Chrome user agent to improve website compatibility
- Locally remembered username/email suggestions on recognized ERPNext, Claude, and ChatGPT login forms
- Styled saved-account menu with filtering and per-account removal
- Accounts are committed to history only after a successful authenticated login is detected
- Memory saver keeps only the selected AI renderer alive and unloads it when the AI panel is hidden
- Multiple independent ERPNext tabs sharing the same authenticated session
- Collapsible and resizable Claude side panel
- ERPNext tab back, forward, reload, new-tab, and close controls
- Claude back, forward, reload, and new-chat controls
- `Ctrl+Shift+A` toggles the Claude panel
- `Ctrl+T` opens an ERPNext tab, `Ctrl+W` closes it, and `Ctrl+Tab` switches tabs
- Overflow-aware searchable tab navigator lists every open ERPNext tab and URL
- Chrome-style adaptive tabs shrink from full titles to compact and favicon-only modes
- Browser-style tab shortcuts, overflow arrows, middle-click close, and closed-tab reopening
- Official QC Styropackaging and Multiplast branding on the app window, installer, executable, and shortcuts
- Existing Claude or ChatGPT subscription sessions remain in their respective websites
- ERP Local FAC tools remain available when the selected AI service has its MCP connector configured
- Windows NSIS/portable and Linux AppImage/DEB packaging

## Development

```bash
npm install
npm start
```

The default ERPNext URL is:

```text
https://desktop-vlfuuk4.tail39f829.ts.net/desk
```

Override it when launching:

```bash
ERPNEXT_URL=https://your-erp.example.com/desk npm start
```

or:

```bash
npm start -- --erp-url=https://your-erp.example.com/desk
```

## Packaging

```bash
npm run dist:linux
npm run dist:windows
```

Artifacts are written to `dist/`. Use the included GitHub Actions workflow to build Windows on a Windows runner and Linux on an Ubuntu runner.

### Install on Linux

- Make the AppImage executable and run it, or install the DEB with your system package installer.

### Run on Windows

- Native CI builds produce an NSIS installer with automatic-update support.
- The locally generated `win-x64-unpacked.tar.gz` archive can also be extracted on Windows; run `ERPNext Claude Desktop.exe` from the extracted `win-unpacked` folder.

Windows SmartScreen may warn about unsigned internal applications. Production distribution should use a Windows code-signing certificate.

## Automatic desktop updates

Installed Windows builds check the public `qcstyrogit-main/qcmc_logic` GitHub releases ten seconds after startup and every four hours. When an update is downloaded, the user can restart immediately or install it when the application is closed later.

To publish a release, increase the version in `package.json` and merge the desktop changes into `main`. GitHub Actions automatically builds the NSIS installer, creates the matching `desktop-vX.Y.Z` release, and publishes it with `latest.yml`. Automatic updates apply to the installed NSIS build, not the portable archive. Version tags can still be pushed manually when a release must be rebuilt deliberately.

## Login history and privacy

The app can remember up to ten ERPNext usernames and ten email addresses per assistant, then suggest them in recognized login fields. Account history is stored only in Electron's local application settings. Passwords are never captured or stored by this feature.

## Important limitation

Claude.ai is loaded as a top-level browser view, not an iframe. Anthropic or an identity provider may still change policies that affect login in embedded Chromium clients. No Claude cookies, tokens, or private APIs are copied by this application.
