#!/bin/bash

APP_NAME=$1
ENV_FILE=${2:-.env}  # defaults to ".env" if not provided

if [ -z "$APP_NAME" ]; then
  echo "Usage: ./push_env_to_heroku.sh <heroku-app-name> [env-file-path]"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ Env file not found: $ENV_FILE"
  exit 1
fi

echo "Pushing config vars from $ENV_FILE to Heroku app: $APP_NAME"

while IFS='=' read -r key value || [ -n "$key" ]; do
  if [[ ! "$key" =~ ^# && -n "$key" ]]; then
    heroku config:set "$key=$value" --app "$APP_NAME"
  fi
done < "$ENV_FILE"

echo "✅ All config vars pushed to $APP_NAME"
