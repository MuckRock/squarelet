# Squarelet

**Squarelet** &middot; [MuckRock][muckrock] &middot; [DocumentCloud][documentcloud] &middot; [DocumentCloud-Frontend][documentcloudfrontend]

User account service for MuckRock and DocumentCloud

## Install

### Software required

1. [docker][docker-install]
2. [python][python-install]
3. [invoke][invoke-install]
4. [mkcert][mkcert-install]

### Installation Steps

Check out the git repository.

```bash
git clone git@github.com:MuckRock/squarelet.git
```

Enter the directory.

```bash
cd squarelet
```

Run the environment initialization script, which will create files with the environment variables needed to run the development environment.

```bash
python initialize_dotenvs.py
```

Set an environment variable that directs `docker compose` to use the `local.yml` file.

```bash
export COMPOSE_FILE=local.yml
```

> A command-line tool like [`direnv`](https://direnv.net/) can load this setting when you enter the project directory. With `direnv` installed, run:
> ```bash
> direnv allow .
> echo export COMPOSE_FILE=local.yml > .envrc
> ```
> `.envrc` is omitted from version control.

Generate local certificates for SSL support.

```bash
inv mkcert
```

Start the docker containers. This will build and start all of the Squarelet session docker images using docker compose. It will bind to port 80 on localhost, so you must not have anything else running on port 80.

```bash
inv up
```

Set `dev.squarelet.com` to point to localhost.

```bash
echo "127.0.0.1   dev.squarelet.com" | sudo tee -a /etc/hosts
```

Enter `dev.squarelet.com` into your browser. You should see the Muckrock Squarelet home page.

### Integrations

The Squarelet project provides an authentication system for MuckRock and DocumentCloud. Therefore, there must be certain things set up within Squarelet before you can begin accessing them individually.

If you are developing on any of our other projects. Follow the following integration steps:

1.  With the Squarelet containers running, in your terminal within the Squarelet folder, open up the bash shell with `inv sh`
2.  Within the bash shell, utilize this command to create your RSA key `./manage.py creatersakey`
3.  Then create a superuser utilizing the following command: `./manage.py createsuperuser`
4.  Exit the bash shell with the command `exit`
5.  In a browser navigate to the admin portal. You can find this portal by using the base Squarelet URL, and appending /admin to the end of it.
6.  Navigate to [Clients](https://dev.squarelet.com/admin/oidc_provider/client/)
7.  Follow the steps for the respective project integrations:
    <details>
    <summary>MuckRock</summary>
    1. Create a client called `MuckRock Dev` <br/>
    2. Make sure the fields have the following values: <br/>

    | Field                                                         | Value                                                                                                        |
    | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
    | Owner                                                         | blank/your user account                                                                                      |
    | Client Type                                                   | Confidential                                                                                                 |
    | Response Types                                                | code (Authorization Code Flow)                                                                               |
    | Redirect URIs (on separate lines)                             | https://dev.muckrock.com/accounts/complete/squarelet https://dev.foiamachine.org/accounts/complete/squarelet |
    | JWT Algorithm                                                 | RS256                                                                                                        |
    | Require Consent?                                              | Unchecked                                                                                                    |
    | Reuse Consent                                                 | Checked                                                                                                      |
    | Client ID                                                     | This will be filled in automatically upon saving                                                             |
    | Client SECRET                                                 | This will be filled in automatically upon saving                                                             |
    | Scopes (separated by whitespace)                              | read_user write_user read_organization write_charge read_auth_token                                          |
    | Post Logout Redirect URIs (on separate lines)                 | https://dev.muckrock.com/ https://dev.foiamachine.org/                                                       |
    | Webhook URL (To make this field appear, Add a client profile) | https://dev.muckrock.com/squarelet/webhook/                                                                  |

    <br/>
    </details>
    <details>
    <summary>DocumentCloud</summary>
    1. Create a client called `DocumentCloud Dev` <br/>
    2. Make sure the fields have the following values: <br/>

    | Field                                                         | Value                                                                                                                     |
    | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
    | Owner                                                         | blank/your user account                                                                                                   |
    | Client Type                                                   | Confidential                                                                                                              |
    | Response Types                                                | code (Authorization Code Flow)                                                                                            |
    | Redirect URIs (on separate lines)                             | https://api.dev.documentcloud.org/accounts/complete/squarelet https://minio.documentcloud.org/accounts/complete/squarelet |
    | JWT Algorithm                                                 | RS256                                                                                                                     |
    | Require Consent?                                              | Unchecked                                                                                                                 |
    | Reuse Consent                                                 | Checked                                                                                                                   |
    | Client ID                                                     | This will be filled in automatically upon saving                                                                          |
    | Client SECRET                                                 | This will be filled in automatically upon saving                                                                          |
    | Scopes (separated by whitespace)                              | read_user read_organization read_auth_token                                                                               |
    | Post Logout Redirect URIs                                     | https://dev.documentcloud.org                                                                                             |
    | Webhook URL (To make this field appear, Add a client profile) | https://api.dev.documentcloud.org/squarelet/webhook/                                                                      |

    </details>

8.  Click save and continue editing. Note down the `Client ID` and `Client SECRET` values. You will need these later.
9.  Make sure in your `.envs/.local/.django` file, there exist values for: `STRIPE_PUB_KEY`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET`.
10. You must restart the Docker Compose session (via the command `docker compose down` followed by `docker compose up`) each time you change a `.django` file for it to take effect.

## Docker info

The development environment is managed via [docker][docker] and docker compose. Please read up on them if you are unfamiliar with them. The docker compose file is `local.yml`. If you would like to run `docker compose` commands directly, please run `export COMPOSE_FILE=local.yml` so you don't need to specify it in every command.

The containers which are run include the following:

- Nginx
  [Nginx][nginx] is a HTTP server which acts as a reverse proxy for the Django application, and allows development of both squarelet and client applications that depend on it (such as MuckRock and DocumentCloud) in parallel. This system is described in more detail in a later section.

- MailHog
  [MailHog][mailhog] is an email testing tool used for development. All emails in development are sent to MailHog, where you can view them in a web based email viewer. To use mailhog, add the following line to your `/etc/hosts`: `127.0.0.1 dev.mailhog.com`. Now navigating your browser to `dev.mailhog.com` will show the mailhog interface, where you can view all the mail sent from the development environment.

- Django
  This is the [Django][django] application

- PostgreSQL
  [PostgreSQL][postgres] is the relational database used to store the data for the Django application

- Redis
  [Redis][redis] is an in-memory datastore, used as a message broker for Celery as well as a cache backend for Django.

- Celery Worker
  [Celery][celery] is a distrubuted task queue for Python, used to run background tasks from Django. The worker is responsible for running the tasks.

- Celery Beat
  The celery beat image is responsible for queueing up periodic celery tasks.

- Vite
  [Vite][vite] builds and bundles static assets for production.
  During development, it provides a server to update and serve assets.

All systems can be brought up using `inv up`. You can rebuild all images using `inv build`. There are various other invoke commands for common tasks interacting with docker, which you can view in the `tasks.py` file.

<details>
<summary>Stopping and Restarting Docker Containers</summary>

Be sure to stop (if needed) all the docker compose sessions from the different integrations (Ctrl-C, or `docker compose down`) and Squarelet (`docker compose down` in Squarelet folder). Then run the Squarelet session using `inv up` in the squarelet folder. **Finally, run `docker compose up` in the integration's folder to begin using the new dotfiles.**

- This will build and start all of the integration docker images using docker compose. It will attach to the Squarelet network which must be already running. You can connect to Squarelet nginx on port 80 and it will serve the appropriate dependent http service, such as DocumentCloud, based on domain as a virtual host. The `local.yml` configuration file has the docker compose details.
- If you do `docker compose down` on Squarelet when none of the other dependent docker compose sessions (such as DocumentCloud) are running, `docker compose down` will delete the Squarelet network. You will have to explicitly bring the whole squarelet docker compose session back up to recreate it and nginx before being able to start a dependent docker compose session (such as DocumentCloud).
- Using `docker compose up -d` rather than `docker compose up` will make a daemon for DocumentCloud as Squarelet defaults to.

</details>

### Networking Setup

Nginx is run in front of Django in this development environment in order to allow development of squarelet and client applications at the same time. This works by aliasing all needed domains to localhost, and allowing Nginx to properly route them. Other projects have their own docker compose files which will have their containers join the squarelet network, so the containers can communicate with each other properly. For more detail, see the Nginx config file at `compose/local/nginx/nginx.conf`.

### Environment Variables

The application is configured with environment variables in order to make it easy to customize behavior in different environments (dev, testing, staging, production, etc). Some of the environment variables may be sensitive information, such as passwords or API tokens to various services. For this reason, they are not to be checked in to version control. In order to assist with the setup of a new development environment, a script called `initialize_dotenvs.py` is provided which will create the files in the expected places, with the variables included. Those which require external accounts will generally be left blank, and you may sign up for an account to use for development and add your own credentials in. You may also add extra configuration here as necessary for your setup.

## Invoke info

Invoke is a task execution library. It is used to allow easy access to common commands used during development. You may look through the `tasks.py` file to see the commands being run. I will go through some of the more important ones here.

### Release

`inv prod` will merge your dev branch into master, and push to GitHub, which will trigger [CodeShip][codeship] to release it to Heroku, as long as all code checks pass. The production site is currently hosted at [https://accounts.muckrock.com/](https://accounts.muckrock.com/).
`inv staging` will push the staging branch to GitHub, which will trigger CodeShip to release it to Heroku, as long as all code checks pass. The staging site is currently hosted at [https://squarelet-staging.herokuapp.com/](https://squarelet-staging.herokuapp.com/).

### Test

`inv test` will run the test suite. By default it will try to reuse the previous test database to save time. If you have changed the schema and need to rebuild the database, run it with the `--create-db` switch.

`inv coverage` will run the test suite and generate a coverage report at `htmlcov/index.html`.

The test suite will be run on CodeShip prior to releasing new code. Please ensure your code passes all tests before trying to release it. Also please add new tests if you develop new code - we try to mantain at least 85% code coverage.

### Code Quality

`inv pylint` will run [pylint][pylint]. It is possible to silence checks, but should only be done in instances where pylint is misinterpreting the code.
`inv format` will format the code using the [black][black] code formatter.

Both linting and formatting are checked on CodeShip. Please ensure your code is linted and formatted correctly before attempting to release changes.

### Run

`inv up` will start all containers in the background.
`inv runserver` will run the Django server in the foreground. Be careful to not have multiple Django servers running at once. Running the server in the foreground is mainly useful for situations where you would like to use an interactive debugger within your application code.
`inv shell` will run an interactive python shell within the Django environment.
`inv sh` will run a bash shell within the Django docker container.
`inv dbshell` will run a postgresql shell.
`inv manage` will allow you to easily run Django manage.py commands.
`inv npm` will allow you to run NPM commands. `inv npm "run build"` should be run to rebuild assets if any javascript or CSS is changed. If you will be editing a lot of javascript or CSS, you can run `inv npm "run dev"`.
`inv heroku` will open a python shell on Heroku.

## Pip Tools

Python dependencies are managed via [pip-tools][pip-tools]. This allows us to keep all of the python dependencies (including underling dependencies) pinned, to allow for consistent execution across development and production environments.

The corresponding files are kept in the `requirements` folder. There are files for `base`, `local`, and `production` environments. `local` is used for development environments and `production` is used for production and staging environments. Both include `base`. For each environment there is an `.in` file and a `.txt` file. The `.in` file is the input file - you list your direct dependencies here. You may specify version constraints here, but do not have to.

Running `inv pip-compile` will compile the `.in` files to the corresponding `.txt` files. This will pin all of the dependencies, and their dependencies, to the latest versions that meet any constraints that have been put on them. You should run this command if you need to add any new dependencies to an `.in` file. Please keep the `.in` files sorted. After running `inv pip-compile`, you will need to run `inv build` to rebuild the docker images with the new dependencies included.

[docker]: https://docs.docker.com/
[nginx]: https://www.nginx.com/
[mailhog]: https://github.com/mailhog/MailHog
[django]: https://www.djangoproject.com/
[postgres]: https://www.postgresql.org/
[redis]: https://redis.io/
[vite]: https://vite.dev/
[celery]: https://docs.celeryproject.org/en/latest/
[invoke]: http://www.pyinvoke.org/
[docker-install]: https://docs.docker.com/install/
[invoke-install]: http://www.pyinvoke.org/installing.html
[python-install]: https://www.python.org/downloads/
[codeship]: https://app.codeship.com/projects/296009
[pylint]: https://www.pylint.org/
[black]: https://github.com/psf/black
[pip-tools]: https://github.com/jazzband/pip-tools
[mkcert-install]: https://github.com/FiloSottile/mkcert#installation
[muckrock]: https://github.com/MuckRock/muckrock
[documentcloud]: https://github.com/MuckRock/documentcloud
[documentcloudfrontend]: https://github.com/MuckRock/documentcloud-frontend
