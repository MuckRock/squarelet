#!/bin/bash

if [ -n "$HEROKU_APP_NAME" ]; then
  heroku pg:copy squarelet-staging::DATABASE_URL DATABASE_URL --app $HEROKU_APP_NAME
fi