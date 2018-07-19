web: gunicorn config.wsgi:application
worker: celery worker --app=squarelet.taskapp --loglevel=info
beat: celery beat --app=squarelet.taskapp --loglevel=info
