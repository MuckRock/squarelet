web: bin/start-nginx gunicorn -c config/gunicorn.conf config.wsgi:application
worker: celery --app=squarelet.taskapp worker --loglevel=info
beat: celery --app=squarelet.taskapp beat --loglevel=info
release: python manage.py migrate --no-input
