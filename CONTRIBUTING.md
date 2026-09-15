# Contributing

Open a focused pull request from a branch based on `dev`. Describe the behavior change, any SQLite migration, and how you checked it. Run the verification commands in `README.md`; changes to the Docker image or release pipeline should also pass the container smoke test in GitHub Actions. Keep real account exports, databases, credentials and signing keys out of Git.

The maintainer promotes reviewed work from `dev` to `main` and creates semantic-version tags from `main`. Public pull requests retain their contributors' authorship; release-branch commits are made by the `mariof1` account.
