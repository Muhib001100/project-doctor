# Publishing this repository

Everything here is already committed to a local git repository on branch
`main`. These are the only remaining steps.

## 1. Set your details

```bash
python configure.py
```

Answer two questions: your GitHub username, and the name for the LICENSE
copyright line. Press Enter to accept the defaults shown.

## 2. Check it runs

```bash
pip install -e ".[dev]"
pytest
project-doctor . --offline
```

63 tests should pass and the self-scan should report roughly 89/100.

## 3. Create the empty GitHub repository

Go to <https://github.com/new>.

- Repository name: `project-doctor`
- Description: `Scan a project or GitHub repo and report what is broken, missing or risky.`
- Visibility: **Public**
- Leave "Add a README", "Add .gitignore" and "Choose a license" **unticked** —
  this repository already has all three.

Click **Create repository**.

## 4. Push

Replace `YOURNAME` with your GitHub username:

```bash
git add -A
git commit -m "Set repository owner"
git remote add origin https://github.com/YOURNAME/project-doctor.git
git push -u origin main
```

If git asks for a password, use a personal access token, not your account
password: <https://github.com/settings/tokens> → Generate new token (classic) →
tick `repo` → copy the token and paste it as the password.

## 5. Confirm CI is green

Open the **Actions** tab on the repository. The `CI` workflow runs the test
suite on five Python versions plus macOS and Windows, then scans the repository
with the tool itself.

## 6. Make it findable

On the repository page, click the gear icon beside **About** and add topics:

```
cli  python  static-analysis  code-quality  linter  github-actions  developer-tools  devtools
```

## 7. Optional: publish to PyPI

Only after the repository is up and CI is green.

1. Create an account at <https://pypi.org/account/register/>.
2. Go to <https://pypi.org/manage/account/publishing/> and add a pending
   publisher:
   - PyPI project name: `project-doctor`
   - Owner: your GitHub username
   - Repository name: `project-doctor`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. In the GitHub repository: **Settings → Environments → New environment**,
   name it exactly `pypi`, then Configure.
4. **Releases → Create a new release**, tag `v0.1.0`, title `v0.1.0`, publish.

The `publish.yml` workflow builds and uploads the package using trusted
publishing, so no API token is stored anywhere.

If the name `project-doctor` is already taken on PyPI, change `name` in
`pyproject.toml` (for example to `project-doctor-cli`) and use that name in
step 2 as well. The command you type stays `project-doctor` either way.
