# Deployment helpers

## VM bootstrap
```bash
bash scripts/bootstrap_all.sh
```

## Production env
Copy `.env.production.example` to `.env` and edit the database credentials.

## systemd templates
Files are provided under `deploy/systemd/`.
Adjust the working directory if needed, then copy them to `/etc/systemd/system/`.

Example:
```bash
sudo cp deploy/systemd/signalmaker-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable signalmaker-api
sudo systemctl start signalmaker-api
```
