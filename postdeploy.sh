#!/bin/bash

echo "Build static files to be collected"
npm ci --include dev
npm run build

echo "Setup Django"
python manage.py migrate --noinput
python manage.py collectstatic --noinput
