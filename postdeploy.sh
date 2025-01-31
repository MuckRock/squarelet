#!/bin/bash

# Build static files to be collected
npm install
npm run build

# Setup Django database and static files
python manage.py migrate --noinput
python manage.py collectstatic --noinput
