#!/usr/bin/env ash

envsubst < /app/config.ini.TEMPLATE > /app/config.ini

while :; do
    python /app/run.py
    echo "Sleeping for ${INTERVAL:-1h}..."
    sleep ${INTERVAL:-1h}
done
