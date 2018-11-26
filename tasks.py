# Third Party
from invoke import task

DOCKER_COMPOSE_RUN_OPT = "docker-compose run {opt} --rm {service} {cmd}"
DOCKER_COMPOSE_RUN_OPT_USER = DOCKER_COMPOSE_RUN_OPT.format(
    opt="-u $(id -u):$(id -g) {opt}", service="{service}", cmd="{cmd}"
)
DOCKER_COMPOSE_RUN = DOCKER_COMPOSE_RUN_OPT.format(
    opt="", service="{service}", cmd="{cmd}"
)
DJANGO_RUN = DOCKER_COMPOSE_RUN.format(service="django", cmd="{cmd}")
DJANGO_RUN_USER = DOCKER_COMPOSE_RUN_OPT_USER.format(
    opt="", service="django", cmd="{cmd}"
)


@task
def staging(c):
    c.run("git push origin staging")


@task
def test(c, path="", reuse_db=False):
    """Run the test suite"""
    if reuse_db:
        reuse_switch = "--reuse-db"
    else:
        reuse_switch = ""
    c.run(
        DOCKER_COMPOSE_RUN_OPT.format(
            opt="-e DJANGO_SETTINGS_MODULE=config.settings.test",
            service="django",
            cmd=f"pytest {reuse_switch} {path}",
        )
    )


@task
def pylint(c):
    """Run the linter"""
    c.run(DJANGO_RUN.format(cmd="pylint squarelet"))


@task
def format(c):
    """Format your code"""
    c.run(
        DJANGO_RUN_USER.format(
            cmd="black squarelet --exclude migrations && isort -rc squarelet"
        )
    )


@task
def runserver(c):
    """Run the development server"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT.format(
            opt="--service-ports --use-aliases", service="django", cmd=""
        )
    )


@task
def shell(c):
    """Run an interactive shell"""
    c.run(DJANGO_RUN.format(cmd="python manage.py shell_plus"), pty=True)


@task
def celeryworker(c):
    """Run a celery worker"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT.format(
            opt="--use-aliases", service="celeryworker", cmd=""
        )
    )


@task
def celerybeat(c):
    """Run the celery scheduler"""
    c.run(
        DOCKER_COMPOSE_RUN_OPT.format(opt="--use-aliases", service="celerybeat", cmd="")
    )


@task
def manage(c, cmd):
    """Run a Django management command"""
    c.run(DJANGO_RUN_USER.format(cmd=f"python manage.py {cmd}"))


@task
def run(c, cmd):
    """Run a command directly on the docker instance"""
    c.run(DJANGO_RUN_USER.format(cmd=cmd))


@task(name="pip-compile")
def pip_compile(c, upgrade=False):
    """Run pip compile"""
    if upgrade:
        upgrade_flag = "--upgrade"
    else:
        upgrade_flag = ""
    c.run(
        DJANGO_RUN.format(
            cmd=f"pip-compile {upgrade_flag} requirements/base.in &&"
            f"pip-compile {upgrade_flag} requirements/local.in &&"
            f"pip-compile {upgrade_flag} requirements/production.in"
        )
    )


@task
def build(c):
    """Build the docker images"""
    c.run("docker-compose build")
