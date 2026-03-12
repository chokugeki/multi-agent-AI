#!/bin/sh
set -e

# Copy the mounted config to a writable location
cp /app/config/config.json /tmp/config.json
cp /app/config/topology.yaml /tmp/topology.yaml

# Replace API keys and endpoints in config.json and topology.yaml with values from the environment
sed -i "s/\"api_key\": \".*\"/\"api_key\": \"${GLOBAL_API_KEY}\"/" /tmp/config.json
sed -i "s|\"api_base\": \"\\\$OLLAMA_API_BASE\"|\"api_base\": \"${OLLAMA_API_BASE}\"|g" /tmp/config.json
sed -i "s|model: \"\\\$MODEL_NAME\"|model: \"${MODEL_NAME}\"|g" /tmp/topology.yaml

# Tell picoclaw to use the new config location
mkdir -p /root/.picoclaw
cp /tmp/config.json /root/.picoclaw/config.json

# Execute the main command
exec "$@"
