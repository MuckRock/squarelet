#!/bin/bash

echo "Build static files to be collected"
npm ci
npm run build

echo "Setup Django database and static files"
python manage.py migrate --noinput
python manage.py collectstatic --noinput
