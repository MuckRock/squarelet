#!/usr/bin/env python
# This will create your initial .env files
# These are not to be checked in to git, as you may populate them
# with confidential information

# Standard Library
import os
import random
import string


def random_string(n):
    return "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(n)
    )


CONFIG = [
    {
        "name": ".django",
        "sections": [
            {
                "name": "General",
                "envvars": [
                    ("USE_DOCKER", "yes"),
                    ("DJANGO_SECRET_KEY", lambda: random_string(20)),
                    ("IPYTHONDIR", "/app/.ipython"),
                    ("REQUESTS_CA_BUNDLE", "/etc/ssl/certs/ca-certificates.crt"),
                ],
            },
            {
                "name": "Redis",
                "description": "Redis is used as a celery broker and as a cache backend",
                "envvars": [("REDIS_URL", "redis://squarelet_redis:6379/0")],
            },
            {
                "name": "Mailgun",
                "url": "https://www.mailgun.com",
                "description": "Mailgun is used for sending mail",
                "envvars": [("MAILGUN_ACCESS_KEY", "")],
            },
            {
                "name": "Stripe",
                "url": "https://stripe.com",
                "description": "Stripe is used for payment processing",
                "envvars": [
                    ("STRIPE_SECRET_KEY", "sk_muckrock"),
                    ("STRIPE_PUB_KEY", "pk_muckrock"),
                    ("STRIPE_WEBHOOK_SECRET", "wh_muckrock"),
                ],
            },
        ],
    },
    {
        "name": ".postgres",
        "sections": [
            {
                "name": "PostgreSQL",
                "envvars": [
                    ("POSTGRES_HOST", "squarelet_postgres"),
                    ("POSTGRES_PORT", "5432"),
                    ("POSTGRES_DB", "squarelet"),
                    ("POSTGRES_USER", lambda: random_string(30)),
                    ("POSTGRES_PASSWORD", lambda: random_string(60)),
                ],
            }
        ],
    },
]


def main():
    print("Initializing the dot env environment for Squarelet development")
    os.makedirs(".envs/.local/", 0o775)
    print("Created the directories")
    for file_config in CONFIG:
        with open(".envs/.local/{}".format(file_config["name"]), "w") as file_:
            for section in file_config["sections"]:
                for key in ["name", "url", "description"]:
                    if key in section:
                        file_.write("# {}\n".format(section[key]))
                file_.write("# {}\n".format("-" * 78))
                for var, value in section["envvars"]:
                    file_.write(
                        "{}={}\n".format(var, value() if callable(value) else value)
                    )
                file_.write("\n")
        print("Created file .envs/.local/{}".format(file_config["name"]))
    print("Initialization Complete")


if __name__ == "__main__":
    main()
