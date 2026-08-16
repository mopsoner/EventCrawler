#!/usr/bin/env bash
set -eux

cd EventCrawler
exec ../.venv/bin/python -c "from app import app; import os; app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5080)), debug=False)"
