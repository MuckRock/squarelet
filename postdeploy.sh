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
  # Restore the most recent backup of muckrock-staging into the review app database
  heroku pg:backups:restore squarelet-staging DATABASE_URL \
    --app "$HEROKU_APP_NAME" \
    --confirm "$HEROKU_APP_NAME"
fi

# No matter what environment we're in, ensure we run any Django migrations.
python manage.py migrate --noinput
