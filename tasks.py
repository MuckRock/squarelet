# Third Party
from invoke import task


@task
def test(c, path="", reuse_db=False):
    """Run the test suite"""
    if reuse_db:
        reuse_switch = "--reuse-db"
    else:
        reuse_switch = ""
    c.run(
        f"docker-compose run -e DJANGO_SETTINGS_MODULE=config.settings.test --rm "
        f"django pytest {reuse_switch} {path}"
    )


@task
def pylint(c):
    """Run the linter"""
    c.run("docker-compose run --rm django pylint squarelet")


@task
def format(c):
    """Format your code"""
    c.run("docker-compose run --rm django black squarelet --exclude migrations")
    c.run("docker-compose run --rm django isort -rc squarelet")


@task
def runserver(c):
    """Run the development server"""
    c.run("docker-compose run --service-ports --rm django")


@task
def shell(c):
    """Run an interactive shell"""
    c.run("docker-compose run --rm django python manage.py shell_plus", pty=True)


@task
def celeryworker(c):
    """Run a celery worker"""
    c.run("docker-compose run --service-ports --rm celeryworker")


@task
def celerybeat(c):
    """Run the celery scheduler"""
    c.run("docker-compose run --service-ports --rm celerybeat")


@task
def manage(c, cmd):
    """Run a Django management command"""
    c.run(f"docker-compose run --rm -u $(id -u):$(id -g) django python manage.py {cmd}")


@task
def pip_compile(c, upgrade=False):
    """Run pip compile"""
    c.run("pip-compile")
