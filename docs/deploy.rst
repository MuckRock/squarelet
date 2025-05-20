Deploy
========

Squarelet is deployed to Heroku.  This page containts the information needed to configure Heroku properly.

Buildpacks
----------

`Buildpacks <https://devcenter.heroku.com/articles/buildpacks>`_ control how your code is deployed on Heroku.

 1. https://github.com/kjwon15/heroku-buildpack-nginx#real-ip
     This buildpack is for running nginx in front of the gunicorn app server.  There is an official nginx buildpack, but we are currently using this fork for the real-up support.  Hopefully this will be merged upstream and we can return to the officially supoorted buildpack.

 2. heroku/python
     This is the official python buildpack


Environment Variables
---------------------

Many settings are controlled through environment variables, as well as confidential information which we do not want to keep in a git repository.  They allow for customizing based on environment (staging, production, etc).

.. envvar:: ALLOW_IPS

    This is only used on the staging server.  It limits who can access the site based on IP.  It is a comma seperated list of <ip address>:<comment> where <ip address> is the IP address to allow and comment is a note of whose IP address it is.
    
.. envvar:: BANDIT_EMAIL

    This is used on staging to specify where all outgoing emails should be sent.  See :envvar:`USE_BANDIT` for more information.

.. envvar:: DATABASE_URL

    This is set by the :ref:`Heroku Postgres <heroku postgres>` add on and should not be edited.

.. envvar:: DJANGO_ACCOUNT_ALLOW_REGISTRATION

    This enables account registration.  It should generally be set to ``True``.

.. envvar:: DJANGO_ADMIN_URL

   This sets the URL for the Django admin.  This is useful for keeping this secret for security purposes.  It should be set to a random value.

.. envvar:: DJANGO_ALLOWED_HOSTS

    This sets the Django settings :setting:`ALLOWED_HOSTS`.  It specifies which domains you may use to access this site.  For staging, it is set to ``$HEROKU_APP.herokuapp.com`` (using the environment variable ``$HEROKU_APP``).  For production it will be set to ``accounts.muckrock.com``.

.. envvar:: DJANGO_AWS_ACCESS_KEY_ID

    This is set to the Access Key ID for Amazon Web Services so that the code may access S3.

.. envvar:: DJANGO_AWS_SECRET_ACCESS_KEY

    This is set to the Secret Access Key for Amazon Web Services so that the code may access S3.

.. envvar:: DJANGO_AWS_STORAGE_BUCKET_NAME

    This is the S3 bucket to use on Amazon Web Services for storing files.

.. envvar:: DJANGO_SECRET_KEY

    This sets :setting:`SECRET_KEY`.  It should be set to a random value.

.. envvar:: DJANGO_SECURE_SSL_REDIRECT

    This sets :setting:`SECURE_SSL_REDIRECT`.  It will redirect HTTP requests to HTTPS requests.  It should be set to ``True``.

.. envvar:: DJANGO_SETTINGS_MODULE

    This controls which module Django loads as the settings module.  It should be set to ``config.settings.production`` for both staging and production.

.. envvar:: FIXIE_URL

    This is set by the :ref:`Fixie <fixie>` add on and should not be edited.  This is only used on staging.

.. envvar:: GUNICORN_WORKERS

    Controls how many `workers <http://docs.gunicorn.org/en/stable/settings.html#workers>`_ the Gunicorn worker will spawn.  This is currently set to ``3``.

.. envvar:: MAILGUN_API_KEY

    This is the API key for mailgun.  It allows us to connect to our mailgun account to send email.

.. envvar:: MAILGUN_DOMAIN

    This is the domain we are using for mailgun.

.. envvar:: NO_PROXY

    This is a standard unix environment variable to specify which hosts do not need to use a proxy.  This is only used for staging.  See `Fixie <fixie>`_ for more details.  It should be set to any URL the site makes outgoing HTTP requests to.  It is currently set to ``.amazonaws.com,.sentry.io,.mailgun.net``.

.. envvar:: PAPERTRAIL_API_TOKEN

    This is set by the :ref:`Papertrail <papertrail>` add on.

.. envvar:: PYTHONHASHSEED

    This should be set to ``random``.  See :envvar:`PYTHONHASHSEED <python:PYTHONHASHSEED>`.

.. envvar:: REDIS_URL

    This is set by the :ref:`Heroku Redis <heroku redis>` add on and should not be edited.

.. envvar:: SENTRY_DSN

    This is the *Data Source Name* required for connecting to Sentry.

.. envvar:: USE_BANDIT

    This enables `Django Email Bandit <https://github.com/caktus/django-email-bandit>`_, which sends all outgoing emails to :envvar:`BANDIT_EMAIL`.  It should only be set to ``True`` on staging.


Add Ons
-------

.. _fixie:
.. object:: Fixie

    This add on is only used for staging.  Since we use `ALLOW_IPS` to restrict access to all of our staging sites by IP address, our staging sites need static IPs in order to communicate with each other via API.  Since Heroku does not assign static IPs, we use Fixie to proxy outgoing HTTP requests, giving us a static IP we can whitelist on the other staging servers.

    We are currently using the Tricycle plan on staging.

.. _heroku postgres:
.. object:: Heroku Postgres

    This is Heroku's hosted postgres service, which we use as our main relational database.

    We are currently using the Hobby Dev plan on staging.  On production, we will use the Standard 0 plan.

.. _heroku redis:
.. object:: Heroku Redis

    This is Heroku's hosted redis service, which we use for both our task broker for celery and for an in memory cache.

    We are currently using the Hobby Dev plan on staging.  On production, we will use the Premium 1 plan.

.. _papertrail:
.. object:: Papertrail
    
    Papertrail is a cloud log management solution.  We use it to keep track of our logs.

    We are currently using the Choklad plan on staging.  On production, we will use the Fixa plan.

