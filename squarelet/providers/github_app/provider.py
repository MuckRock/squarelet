# Third Party
from allauth.socialaccount.providers.github.provider import (
    GitHubAccount,
    GitHubProvider,
)


class GitHubAppProvider(GitHubProvider):
    id = "github_app"
    name = "GitHub App"
    account_class = GitHubAccount


provider_classes = [GitHubAppProvider]
