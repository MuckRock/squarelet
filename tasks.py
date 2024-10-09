# Standard Library
from pathlib import Path

# Third Party
from invoke import task

DOCKER_COMPOSE_RUN_OPT = "docker compose -f local.yml run {opt} --rm {service} {cmd}"
DOCKER_COMPOSE_RUN_OPT_USER = DOCKER_COMPOSE_RUN_OPT.format(
    opt="-u $(id -u):$(id -g) {opt}", service="{service}", cmd="{cmd}"
)
DOCKER_COMPOSE_RUN = DOCKER_COMPOSE_RUN_OPT.format(
    opt="", service="{service}", cmd="{cmd}"
)
DJANGO_RUN = DOCKER_COMPOSE_RUN.format(service="squarelet_django", cmd="{cmd}")
DJANGO_RUN_USER = DOCKER_COMPOSE_RUN_OPT_USER.format(
    opt="-e HOME=/app", service="squarelet_django", cmd="{cmd}"
)

# Release
# --------------------------------------------------------------------------------


@task(aliases=["prod", "p"])
def production(c):
    """Merge your dev branch into master and push to production"""
    c.run("git pull origin dev")
    c.run("git checkout master")
    c.run("git pull origin master")
    c.run("git merge dev")
    c.run("git push origin master")
    c.run("git checkout dev")
    c.run("git push origin dev")


@task
def staging(c):
    """Push out staging"""
    c.run("git push origin staging")


# Test
# --------------------------------------------------------------------------------


@task
def test(c, path="squarelet", create_db=False, ipdb=False, warnings=False):
    """Run the test suite"""
    create_switch = "--create-db" if create_db else ""
    ipdb_switch = "--pdb --pdbcls=IPython.terminal.debugger:Pdb" if ipdb else ""
    warnings = "-e PYTHONWARNINGS=always" if warnings else ""

    c.run(
        DOCKER_COMPOSE_RUN_OPT_USER.format(
            opt=f"-e DJANGO_SETTINGS_MODULE=config.settings.test {warnings}",
            service="squarelet_django",
            cmd=f"pytest {create_switch} {ipdb_switch} {path}",
        ),
        pty=True,
    )


@task
def coverage(c):
    """Run the test suite with coverage report"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT_USER.format(
            opt="-e DJANGO_SETTINGS_MODULE=config.settings.test",
            service="squarelet_django",
            cmd=f"coverage erase",
        )
    )
    c.run(
        DOCKER_COMPOSE_RUN_OPT_USER.format(
            opt="-e DJANGO_SETTINGS_MODULE=config.settings.test",
            service="squarelet_django",
            cmd=f"coverage run -m py.test squarelet",
        )
    )
    c.run(
        DOCKER_COMPOSE_RUN_OPT_USER.format(
            opt="-e DJANGO_SETTINGS_MODULE=config.settings.test",
            service="squarelet_django",
            cmd=f"coverage html",
        )
    )


# Code Quality
# --------------------------------------------------------------------------------


@task
def pylint(c):
    """Run the linter"""
    c.run(DJANGO_RUN.format(cmd="pylint squarelet"))


@task
def format(c):
    """Format your code"""
    c.run(
        DJANGO_RUN_USER.format(
            cmd="black squarelet --exclude migrations && "
            "black config/urls.py && "
            "black config/settings && "
            "isort --recursive squarelet && "
            "isort config/urls.py && "
            "isort --recursive config/settings"
        )
    )


# Run
# --------------------------------------------------------------------------------


@task
def up(c):
    """Start the docker images"""
    c.run("docker compose up -d")


@task
def runserver(c):
    """Run the development server"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT.format(
            opt="--service-ports --use-aliases", service="squarelet_django", cmd=""
        )
    )


@task
def celeryworker(c):
    """Run a celery worker"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT.format(
            opt="--use-aliases", service="squarelet_celeryworker", cmd=""
        )
    )


@task
def celerybeat(c):
    """Run the celery scheduler"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT.format(
            opt="--use-aliases", service="squarelet_celerybeat", cmd=""
        )
    )


@task
def shell(c, opts=""):
    """Run an interactive python shell"""
    c.run(DJANGO_RUN.format(cmd=f"python manage.py shell_plus {opts}"), pty=True)


@task
def sh(c):
    """Run an interactive shell"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT_USER.format(
            opt="--use-aliases", service="squarelet_django", cmd="sh"
        ),
        pty=True,
    )


@task
def dbshell(c, opts=""):
    """Run an interactive db shell"""
    c.run(DJANGO_RUN.format(cmd=f"python manage.py dbshell {opts}"), pty=True)


@task(aliases=["m"])
def manage(c, cmd):
    """Run a Django management command"""
    c.run(DJANGO_RUN_USER.format(cmd=f"python manage.py {cmd}"))


@task
def run(c, cmd):
    """Run a command directly on the docker instance"""
    c.run(DJANGO_RUN_USER.format(cmd=cmd))


@task
def npm(c, cmd):
    """Run an NPM command"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT.format(
            opt="--workdir /app", service="squarelet_django", cmd=f"npm {cmd}"
        )
    )


@task
def heroku(c, staging=False):
    """Run commands on heroku"""
    if staging:
        app = "squarelet-staging"
    else:
        app = "squarelet"
    c.run(f"heroku run --app {app} python manage.py shell_plus", pty=True)


# Dependency Management
# --------------------------------------------------------------------------------


@task(name="pip-compile")
def pip_compile(c, upgrade=False, package=None):
    """Run pip compile"""
    if package:
        upgrade_flag = f"--upgrade-package {package}"
    elif upgrade:
        upgrade_flag = "--upgrade"
    else:
        upgrade_flag = ""
    c.run(
        DJANGO_RUN_USER.format(
            cmd='sh -c "'
            f"pip-compile {upgrade_flag} requirements/base.in && "
            f"pip-compile {upgrade_flag} requirements/local.in && "
            f"pip-compile {upgrade_flag} requirements/production.in"
            '"'
        )
    )


@task
def build(c):
    """Build the docker images"""
    c.run("docker compose -f local.yml build")


# Database populating
# --------------------------------------------------------------------------------


@task(name="populate-db")
def populate_db(c, db_name="squarelet"):
    """Populate the local DB with the data from heroku"""
    # https://devcenter.heroku.com/articles/heroku-postgres-import-export
    # this doesnt work due to version mismatch in postgres
    # work around is to heroku pg:backups:download
    # and manual pg_restore
    #  pg_restore --verbose --clean --no-acl --no-owner -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB latest.dump

    confirm = input(
        f"This will over write your local database ({db_name}).  "
        "Are you sure you want to continue? [y/N]"
    )
    if confirm.lower() not in ["y", "yes"]:
        return

    c.run(
        DJANGO_RUN_USER.format(
            cmd=f'sh -c "dropdb {db_name} && heroku pg:pull DATABASE {db_name} --app squarelet '
            '--exclude-table-data=public.reversion_version"'
        )
    )


@task(name="update-staging-db")
def update_staging_db(c):
    """Update the staging database"""
    c.run("heroku maintenance:on --app squarelet-staging")
    c.run("heroku pg:copy squarelet::DATABASE_URL DATABASE_URL --app squarelet-staging")
    c.run("heroku maintenance:off --app squarelet-staging")


# Static file populating
# --------------------------------------------------------------------------------


@task(name="sync-aws")
def sync_aws(c):
    """Sync images from AWS to match the production database"""

    folders = ["account_images", "avatars", "org_avatars"]
    for folder in folders:
        c.run(
            f"aws s3 sync s3://squarelet/media/{folder} " f"./squarelet/media/{folder}"
        )


@task(name="sync-aws-staging")
def sync_aws_staging(c):
    """Sync images from AWS to match the production database"""

    folders = ["account_images", "avatars", "org_avatars"]
    for folder in folders:
        c.run(
            f"aws s3 sync s3://squarelet/media/{folder} "
            f"s3://squarelet-staging/media/{folder}"
        )


# Setup
# --------------------------------------------------------------------------------
@task
def mkcert(c):
    """Make SSL certificates for local development"""
    certs_dir = Path("./config/certs/")
    if not certs_dir.exists():
        certs_dir.mkdir(parents=True, exist_ok=True)
    with c.cd(str(certs_dir)):
        c.run(
            "CAROOT=. mkcert "
            "-install "
            "-cert-file dev.squarelet.com.pem "
            "-key-file dev.squarelet.com-key.pem "
            "dev.squarelet.com "
            '"*.dev.documentcloud.org" '
            "dev.muckrock.com "
            "dev.foiamachine.org "
            "dev.mailhog.com"
        )
