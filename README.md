# Squarelet

User account service for MuckRock and DocumentCloud

## Install

### Software required

1. [docker][docker-install]
2. [docker-compose][docker-compose-install]
3. [python][python-install]
4. [invoke][invoke-install]
5. [mkcert][mkcert-install]

### Installation Steps

1. Check out the git repository - `git clone git@github.com:MuckRock/squarelet.git`
2. Enter the directory - `cd squarelet`
3. Run the dotenv initialization script - `python initialize_dotenvs.py`
This will create files with the environment variables needed to run the development environment.
4. You need to provide valid testing values for `STRIPE_PUB_KEYS`, `STRIPE_SECRET_KEYS` and set `STRIPE_WEBHOOK_SECRETS=None` from the MuckRock team (multiple values are comma separated only, no square braces) 
      - You must always fully `docker-compose down` or Ctrl-C each time you change a `.django` file of a docker-compose session for it to take effect.
5. Set the environment variable `export COMPOSE_FILE=local.yml` in each of your command lines.
6. Generate local certificates - `inv mkcert`
7. Start the docker images - `inv up`
This will build and start all of the Squarelet session docker images using docker-compose.  It will bind to port 80 on localhost, so you must not have anything else running on port 80. The "invoke" tasks from `tasks.py` specify the `local.yml` configuration file for docker-compose.
8. Set `dev.squarelet.com` to point to localhost - `sudo echo "127.0.0.1   dev.squarelet.com" >> /etc/hosts`
9. Enter `dev.squarelet.com` into your browser - you should see the Muckrock Squarelet home page.
10. Follow the instructions for integration in a platform app such as ["Squarelet Integration" on MuckRock](https://github.com/muckrock/muckrock/#squarelet-integration) documentation or in [the DocumentCloud](https://github.com/muckRock/documentcloud) documentation.

## Docker info

The development environment is managed via [docker][docker] and [docker compose][docker-compose].  Please read up on them if you are unfamiliar with them.  The docker compose file is `local.yml`.  If you would like to run `docker-compose` commands directly, please run `export COMPOSE_FILE=local.yml` so you don't need to specify it in every command.

The containers which are run include the following:

* Nginx
[Nginx][nginx] is a HTTP server which acts as a reverse proxy for the Django application, and allows development of both squarelet and client applications that depend on it (such as MuckRock and DocumentCloud) in parallel.  This system is described in more detail in a later section.

* MailHog
[MailHog][mailhog] is an email testing tool used for development.  All emails in development are sent to MailHog, where you can view them in a web based email viewer.  To use mailhog, add the following line to your `/etc/hosts`: `127.0.0.1 dev.mailhog.com`.  Now navigating your browser to `dev.mailhog.com` will show the mailhog interface, where you can view all the mail sent from the development environment.

* Django
This is the [Django][django] application

* PostgreSQL
[PostgreSQL][postgres] is the relational database used to store the data for the Django application

* Redis
[Redis][redis] is an in-memory datastore, used as a message broker for Celery as well as a cache backend for Django.

* Celery Worker
[Celery][celery] is a distrubuted task queue for Python, used to run background tasks from Django.  The worker is responsible for running the tasks.

* Celery Beat
The celery beat image is responsible for queueing up periodic celery tasks.

All systems can be brought up using `inv up`.  You can rebuild all images using `inv build`.  There are various other invoke commands for common tasks interacting with docker, which you can view in the `tasks.py` file.
### Networking Setup

Nginx is run in front of Django in this development environment in order to allow development of squarelet and client applications at the same time.  This works by aliasing all needed domains to localhost, and allowing Nginx to properly route them.  Other projects have their own docker compose files which will have their containers join the squarelet network, so the containers can communicate with each other properly.  For more detail, see the Nginx config file at `compose/local/nginx/nginx.conf`.

### Environment Variables

The application is configured with environment variables in order to make it easy to customize behavior in different environments (dev, testing, staging, production, etc).  Some of the environment variables may be sensitive information, such as passwords or API tokens to various services.  For this reason, they are not to be checked in to version control.  In order to assist with the setup of a new development environment, a script called `initialize_dotenvs.py` is provided which will create the files in the expected places, with the variables included.  Those which require external accounts will generally be left blank, and you may sign up for an account to use for development and add your own credentials in.  You may also add extra configuration here as necessary for your setup.

## Invoke info

Invoke is a task execution library.  It is used to allow easy access to common commands used during development.  You may look through the `tasks.py` file to see the commands being run.  I will go through some of the more important ones here.

### Release
`inv prod` will merge your dev branch into master, and push to GitHub, which will trigger [CodeShip][codeship] to release it to Heroku, as long as all code checks pass.  The production site is currently hosted at [https://accounts.muckrock.com/](https://accounts.muckrock.com/).
`inv staging` will push the staging branch to GitHub, which will trigger CodeShip to release it to Heroku, as long as all code checks pass.  The staging site is currently hosted at [https://squarelet-staging.herokuapp.com/](https://squarelet-staging.herokuapp.com/).

### Test
`inv test` will run the test suite.  By default it will try to reuse the previous test database to save time.  If you have changed the schema and need to rebuild the database, run it with the `--create-db` switch.

`inv coverage` will run the test suite and generate a coverage report at `htmlcov/index.html`.

The test suite will be run on CodeShip prior to releasing new code.  Please ensure your code passes all tests before trying to release it.  Also please add new tests if you develop new code - we try to mantain at least 85% code coverage.

### Code Quality
`inv pylint` will run [pylint][pylint].  It is possible to silence checks, but should only be done in instances where pylint is misinterpreting the code.
`inv format` will format the code using the [black][black] code formatter.

Both linting and formatting are checked on CodeShip.  Please ensure your code is linted and formatted correctly before attempting to release changes.

### Run
`inv up` will start all containers in the background.
`inv runserver` will run the Django server in the foreground.  Be careful to not have multiple Django servers running at once.  Running the server in the foreground is mainly useful for situations where you would like to use an interactive debugger within your application code.
`inv shell` will run an interactive python shell within the Django environment.
`inv sh` will run a bash shell within the Django docker comtainer.
`inv dbshell` will run a postgresql shell.
`inv manage` will allow you to easily run Django manage.py commands.
`inv npm` will allow you to run NPM commands.  `inv npm "run build"` should be run to rebuild assets if any javascript or CSS is changed. If you will be editing a lot of javascript or CSS, you can run `inv npm "run dev"`.
`inv heroku` will open a python shell on Heroku.

## Pip Tools

Python dependencies are managed via [pip-tools][pip-tools].  This allows us to keep all of the python dependencies (including underling dependencies) pinned, to allow for consistent execution across development and production environments.

The corresponding files are kept in the `requirements` folder.  There are files for `base`, `local`, and `production` environments.  `local` is used for development environments and `production` is used for production and staging environments.  Both include `base`.  For each environment there is an `.in` file and a `.txt` file.  The `.in` file is the input file - you list your direct dependencies here.  You may specify version constraints here, but do not have to.

Running `inv pip-compile` will compile the `.in` files to the corresponding `.txt` files.  This will pin all of the dependencies, and their dependencies, to the latest versions that meet any constraints that have been put on them.  You should run this command if you need to add any new dependencies to an `.in` files.  Please keep the `.in` files sorted.  After running `inv pip-compile`, you will need to run `inv build` to rebuild the docker images with the new dependencies included.

[docker]: https://docs.docker.com/
[docker-compose]: https://docs.docker.com/compose/
[nginx]: https://www.nginx.com/
[mailhog]: https://github.com/mailhog/MailHog
[django]: https://www.djangoproject.com/
[postgres]: https://www.postgresql.org/
[redis]: https://redis.io/
[celery]: https://docs.celeryproject.org/en/latest/
[invoke]: http://www.pyinvoke.org/
[docker-install]: https://docs.docker.com/install/
[docker-compose-install]: https://docs.docker.com/compose/install/
[invoke-install]: http://www.pyinvoke.org/installing.html
[python-install]: https://www.python.org/downloads/
[codeship]: https://app.codeship.com/projects/296009
[pylint]:  https://www.pylint.org/
[black]: https://github.com/psf/black
[pip-tools]: https://github.com/jazzband/pip-tools
[mkcert-install]: https://github.com/FiloSottile/mkcert#installation
