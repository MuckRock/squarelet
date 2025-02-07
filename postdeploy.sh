#!/bin/bash

echo "Build static files to be collected"
npm ci --include dev
npm run build
ls -la frontend/dist # debug

echo "Setup Django"
python manage.py migrate --noinput
python manage.py collectstatic --noinput -v 3 # verbose for debugging
