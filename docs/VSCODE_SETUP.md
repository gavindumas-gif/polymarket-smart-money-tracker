# VS Code Setup

The following extensions were installed automatically with `code --install-extension`:

- `charliermarsh.ruff`
- `ms-azuretools.vscode-docker`
- `ms-azuretools.vscode-containers`
- `qwtel.sqlite-viewer`

Already installed before this project:

- `ms-python.python`
- `ms-python.vscode-pylance`
- `ms-python.debugpy`
- `ms-python.vscode-python-envs`

Manual commands if you need to reinstall them:

```powershell
code --install-extension ms-python.python --force
code --install-extension ms-python.vscode-pylance --force
code --install-extension charliermarsh.ruff --force
code --install-extension ms-azuretools.vscode-docker --force
code --install-extension qwtel.sqlite-viewer --force
```

Note: the VS Code CLI printed non-fatal Crashpad/log permission warnings in this environment, but extension install and listing succeeded.

## Run And Debug

Open the `polymarket-smart-money-tracker` folder itself in VS Code. The parent `New project` folder contains several unrelated projects, so VS Code will not automatically use this project's `.vscode` launch settings from there.

Use **Run and Debug** and choose one of:

- `PM Tracker: Dry Run`
- `PM Tracker: Live Once`
- `PM Tracker: Dashboard`
- `PM Tracker: Web Dashboard`
- `PM Tracker: Init DB`

The launch configs run `polymarket_tracker.cli` as a module with `PYTHONPATH` pointed at `src`, which matches this repository's package layout.

Useful tasks are also available from **Terminal > Run Task**:

- `PM Tracker: Install Dev`
- `PM Tracker: Test`
- `PM Tracker: Dry Run`
- `PM Tracker: Web Dashboard`
- `PM Tracker: Verify`
