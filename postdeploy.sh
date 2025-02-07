#!/bin/bash

if [ -n "$HEROKU_APP_NAME" ]; then
  heroku run "heroku pg:copy squarelet-staging::DATABASE_URL DATABASE_URL --app $HEROKU_APP_NAME --confirm $HEROKU_APP_NAME" -a $HEROKU_APP_NAME
fi