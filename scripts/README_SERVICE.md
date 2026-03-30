Service installation instructions
===============================

1. Copy the unit file to systemd

   As root (or using sudo), copy the template to `/etc/systemd/system/` and edit it:

   sudo cp deploy/jira_mcp.service /etc/systemd/system/jira_mcp.service
   sudo chown root:root /etc/systemd/system/jira_mcp.service
   sudo nano /etc/systemd/system/jira_mcp.service

   - Update `User=` to the account that should run the service (e.g. `www-data` or your user).
   - Update `WorkingDirectory=` and the `PATH`/`ExecStart` to match your project path and virtualenv.

2. Reload systemd and enable the service

   sudo systemctl daemon-reload
   sudo systemctl enable --now jira_mcp.service

3. Check status and logs

   sudo systemctl status jira_mcp.service
   sudo journalctl -u jira_mcp.service -f

Notes
- If you prefer environment variables from a file, add an `EnvironmentFile=/etc/default/jira_mcp` line under the `[Service]` section and create that file with KEY=VALUE lines.
- On systems without systemd, consider using `supervisord` or another process manager.
