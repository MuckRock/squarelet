#!/bin/bash

# Check that the script is running in a Heroku review app.
#
# This is inferred from the presence of a HEROKU_APP_NAME environment variable,
# which is automatically injected by Heroku into review apps.
#
# By checking that we're in a "staging" environment, we have confidence that we're
# only copying staging data into an environment that expects to receive it.
set -e
if [ -n "$HEROKU_APP_NAME" ] && [ "$DJANGO_ENV" = "staging" ]; then
  LATEST_BACKUP=$(heroku pg:backups --app squarelet-staging | awk '/b[0-9]+/ {print $1; exit}')
  heroku pg:backups:restore "squarelet-staging::$LATEST_BACKUP" DATABASE_URL \
    --app "$HEROKU_APP_NAME" \
    --confirm "$HEROKU_APP_NAME"
fi

# No matter what environment we're in, ensure we run any Django migrations.
python manage.py migrate --noinput

# Register a per-review-app Stripe webhook endpoint so that Stripe events are
# delivered to this app's URL instead of sharing the staging endpoint.
#
# Requires:
#   HEROKU_APP_NAME  – set automatically by Heroku for review apps
#   STRIPE_SECRET_KEY – Stripe API key (inherited from parent pipeline app)
#   HEROKU_API_KEY   – Heroku Platform API token (set on the parent pipeline app
#                      so it is inherited by review apps)
if [ -n "$HEROKU_APP_NAME" ] && [ -n "$STRIPE_SECRET_KEY" ]; then
  APP_URL="https://${HEROKU_APP_NAME}.herokuapp.com"
  WEBHOOK_URL="${APP_URL}/organizations/~stripe_webhook/"

  echo "Registering Stripe webhook endpoint for ${WEBHOOK_URL} ..."

  if ! RESPONSE=$(curl -sf -X POST https://api.stripe.com/v1/webhook_endpoints \
    -u "${STRIPE_SECRET_KEY}:" \
    -d "url=${WEBHOOK_URL}" \
    -d "enabled_events[]=charge.succeeded" \
    -d "enabled_events[]=customer.updated" \
    -d "enabled_events[]=customer.subscription.updated" \
    -d "enabled_events[]=customer.subscription.deleted" \
    -d "enabled_events[]=invoice.created" \
    -d "enabled_events[]=invoice.finalized" \
    -d "enabled_events[]=invoice.paid" \
    -d "enabled_events[]=invoice.payment_failed" \
    -d "enabled_events[]=invoice.marked_uncollectible" \
    -d "enabled_events[]=invoice.voided"); then
    echo "Warning: Stripe webhook registration failed, continuing anyway."
  else
    ENDPOINT_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
    SIGNING_SECRET=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['secret'])")

    echo "Registered Stripe webhook endpoint: ${ENDPOINT_ID}"

    # Store the signing secret and endpoint ID as config vars so the app can
    # verify webhook signatures, and so predestroy.sh can clean up the endpoint.
    curl -sf -X PATCH "https://api.heroku.com/apps/${HEROKU_APP_NAME}/config-vars" \
      -H "Accept: application/vnd.heroku+json; version=3" \
      -H "Authorization: Bearer ${HEROKU_API_KEY}" \
      -H "Content-Type: application/json" \
      -d "{\"STRIPE_WEBHOOK_SECRET\": \"${SIGNING_SECRET}\", \"STRIPE_WEBHOOK_ENDPOINT_ID\": \"${ENDPOINT_ID}\"}" \
      || echo "Warning: Failed to store Stripe config vars, continuing anyway."

    echo "Stripe webhook secret and endpoint ID stored as config vars."
  fi
fi
