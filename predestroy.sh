#!/bin/bash

# Deregister the per-review-app Stripe webhook endpoint when the review app
# is destroyed (PR closed / pipeline teardown).
#
# Requires:
#   HEROKU_APP_NAME          – set automatically by Heroku for review apps
#   STRIPE_SECRET_KEY        – Stripe API key
#   STRIPE_WEBHOOK_ENDPOINT_ID – stored by postdeploy.sh as a config var
#   HEROKU_API_KEY           – Heroku Platform API token
set -e

if [ -n "$HEROKU_APP_NAME" ] && [ -n "$STRIPE_SECRET_KEY" ] && \
   [ -n "$STRIPE_WEBHOOK_ENDPOINT_ID" ]; then

  echo "Deregistering Stripe webhook endpoint ${STRIPE_WEBHOOK_ENDPOINT_ID} ..."

  curl -sf -X DELETE \
    "https://api.stripe.com/v1/webhook_endpoints/${STRIPE_WEBHOOK_ENDPOINT_ID}" \
    -u "${STRIPE_SECRET_KEY}:"

  echo "Stripe webhook endpoint ${STRIPE_WEBHOOK_ENDPOINT_ID} deleted."
fi
