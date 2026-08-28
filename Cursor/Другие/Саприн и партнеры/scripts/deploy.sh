#!/usr/bin/env bash
# Deploy Sapirin parser+job to VPS.
set -euo pipefail

HOST="${SAPRIN_HOST:-168.222.202.68}"
SSH_KEY="${SAPRIN_SSH_KEY:-$HOME/.ssh/saprin_id_rsa}"
REMOTE_USER="${SAPRIN_SSH_USER:-root}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ssh_cmd=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "${REMOTE_USER}@${HOST}")
scp_cmd=(scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -r)

echo "==> Sync parser + job (code only, not .env)"
"${ssh_cmd[@]}" 'mkdir -p /opt/saprin/parser /opt/saprin/job/data /opt/saprin/data /opt/saprin/logs'
"${scp_cmd[@]}" "$ROOT/parser/api" "$ROOT/parser/scraper" "$ROOT/parser/requirements.txt" \
  "${REMOTE_USER}@${HOST}:/opt/saprin/parser/"
# directory JSON may be large — sync if present
if [[ -f "$ROOT/parser/directory/courts-ru.json" ]]; then
  "${scp_cmd[@]}" "$ROOT/parser/directory/courts-ru.json" \
    "${REMOTE_USER}@${HOST}:/opt/saprin/parser/directory/"
fi
"${scp_cmd[@]}" "$ROOT/job/bitrix.py" "$ROOT/job/triggers.py" "$ROOT/job/create_uf_fields.py" \
  "$ROOT/job/requirements.txt" "$ROOT/job/.env.example" \
  "${REMOTE_USER}@${HOST}:/opt/saprin/job/"

echo "==> venv deps"
"${ssh_cmd[@]}" '/opt/saprin/venv/bin/pip install -q -r /opt/saprin/parser/requirements.txt
  /opt/saprin/venv/bin/pip install -q -r /opt/saprin/job/requirements.txt
  chown -R saprin:saprin /opt/saprin/parser /opt/saprin/job /opt/saprin/data /opt/saprin/logs'

echo "==> systemd"
"${scp_cmd[@]}" "$ROOT/deploy/saprin-parser.service" \
  "$ROOT/deploy/saprin-job-weekly.service" "$ROOT/deploy/saprin-job-weekly.timer" \
  "$ROOT/deploy/saprin-job-daily.service" "$ROOT/deploy/saprin-job-daily.timer" \
  "${REMOTE_USER}@${HOST}:/etc/systemd/system/"
"${ssh_cmd[@]}" 'systemctl daemon-reload
  systemctl enable --now saprin-parser.service
  systemctl enable --now saprin-job-weekly.timer saprin-job-daily.timer
  systemctl restart saprin-parser.service
  systemctl --no-pager --full status saprin-parser.service | head -15
  systemctl list-timers --all | grep saprin || true
'
echo "Done. Secrets stay in /opt/saprin/*/.env (mode 600)."
