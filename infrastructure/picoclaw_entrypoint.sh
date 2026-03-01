#!/bin/sh
set -e

# Copy the mounted config to a writable location
cp /app/config/config.json /tmp/config.json

# Replace API keys in config.json with the one from the environment
sed -i "s/\"api_key\": \".*\"/\"api_key\": \"${GLOBAL_API_KEY}\"/" /tmp/config.json

# Tell picoclaw to use the new config location
mkdir -p /root/.picoclaw
cp /tmp/config.json /root/.picoclaw/config.json

# Execute the main command
exec "$@"
