#!/bin/sh

# Generate the nginx config from the template according to the E2E_PROFILE environment variable
# If the E2E_PROFILE is dev, use the frontend-dev service, otherwise use the frontend service

set -e

# Set FRONTEND_SUFFIX based on E2E_PROFILE
if [ "$E2E_PROFILE" = "dev" ]; then
    export FRONTEND_SERVICE_NAME="frontend-dev"
else
    export FRONTEND_SERVICE_NAME="frontend"
fi

# Generate nginx config from template
envsubst '${FRONTEND_SERVICE_NAME}' < /etc/nginx/templates/e2e.conf.template > /etc/nginx/conf.d/default.conf

echo "Generated nginx config for E2E_PROFILE=${E2E_PROFILE:-e2e} (FRONTEND_SERVICE_NAME=${FRONTEND_SERVICE_NAME})"

# Start nginx
exec nginx -g 'daemon off;'


