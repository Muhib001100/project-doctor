# Publishing this repository

Everything is already committed to a local git repository on branch `main`.

## The short version

From inside this folder:

```bash
python publish.py
```

It asks for your GitHub username and the name for the LICENSE, writes both into
the project, installs the package, runs the test suite, commits, and — if the
GitHub CLI is installed and signed in — creates the public repository and pushes
it. If the CLI is not there, it prints the two commands you need to finish.

To get the automatic path, install the GitHub CLI once from
<https://cli.github.com>, run `gh auth login`, then run `python publish.py`.

The script never sees your password or token. Authentication is handled by the
GitHub CLI or by git.

## Doing it by hand instead

1. Run `python publish.py` and let it stop at the last step, so your details and
   the test run are still done for you.
2. Open <https://github.com/new>.
   - Repository name: `project-doctor`
   - Description: `Scan a project or GitHub repo and report what is broken, missing or risky.`
   - Visibility: **Public**
   - Leave "Add a README", "Add .gitignore" and "Choose a license" **unticked**.
     This repository already has all three.
3. Click **Create repository**.
4. Back in the terminal, replacing `YOURNAME`:

```bash
git remote add origin https://github.com/YOURNAME/project-doctor.git
git push -u origin main
```

If git asks for a password, use a personal access token instead of your account
password: <https://github.com/settings/tokens> → Generate new token (classic) →
tick `repo` → paste the token as the password.

## After the push

Open the **Actions** tab. The `CI` workflow runs the test suite on five Python
versions plus macOS and Windows, then scans the repository with the tool itself.

Then click the gear icon beside **About** and add topics:

```
cli  python  static-analysis  code-quality  linter  github-actions  developer-tools  devtools
```

`publish.py` sets these automatically when it uses the GitHub CLI.

## Optional: publish to PyPI

Only after the repository is up and CI is green.

1. Create an account at <https://pypi.org/account/register/>.
2. Go to <https://pypi.org/manage/account/publishing/> and add a pending
   publisher:
   - PyPI project name: `project-doctor`
   - Owner: your GitHub username
   - Repository name: `project-doctor`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. In the GitHub repository: **Settings → Environments → New environment**, name
   it exactly `pypi`, then Configure.
4. **Releases → Create a new release**, tag `v0.1.0`, title `v0.1.0`, publish.

The `.github/workflows/publish.yml` workflow builds and uploads the package
using trusted publishing, so no API token is stored anywhere.

If the name `project-doctor` is already taken on PyPI, change `name` in
`pyproject.toml` (for example to `project-doctor-cli`) and use that name in
step 2 as well. The command you type stays `project-doctor` either way.
