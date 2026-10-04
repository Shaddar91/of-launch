# of-launch

of-launch is the deployment dashboard for the OF cluster. You sign in, choose an environment, a service and a build, and it deploys that build and records who deployed what in MySQL. It is a Flask app set up here for one cluster, `of`, with two services: the `of-web` single-page frontend and the `of-api` Flask API on EKS.

| Deploy type | What a deploy does |
|---|---|
| `frontend` | downloads the build tarball from the artifact bucket, syncs it into the service's deploy bucket, invalidates its CloudFront distribution |
| `eks` | commits the image tag to the service's Helm values file through the GitHub API, then syncs its Argo CD app |
| `worker`, `cron` | registers the artifact as a CodeDeploy revision and starts a deployment |

Pages: `/deploy`, `/status` (CodeDeploy deployments, Argo CD apps, cron jobs, batches), `/deployment-history`, `/current-state` and `/admin/users`. `/current-state` shows no services in any environment, because `get_ecs_state` in `of_launch/utils/aws.py` returns an empty list. `admin` users deploy anywhere and manage users, `production-executor` users deploy anywhere, and `shared-executor` users deploy only to the environments in `OF_SHARED_EXECUTOR_ENVIRONMENTS`, or everywhere except `production` when it is empty.

## Clusters

`config/clusters.json` is the cluster registry. Each key under `clusters` is one cluster: the names of the two variables that hold its Argo CD URL and token, its environments, and its services grouped by deploy type. A `${NAME}` in a value is read from the environment when the file loads, and `{environment}` becomes the environment being deployed. Each environment belongs to one cluster, and the loader refuses a file that lists an environment under two clusters.

To add a cluster, add one entry under `clusters` and set the two variables it names. `tests/test_clusters.py` and `tests/test_services.py` load this one and deploy `of-api` to `staging` through it:

```json
"lab": {
  "display_name": "Lab cluster",
  "argocd_url_env": "ARGOCD_LAB_URL",
  "argocd_token_env": "ARGOCD_LAB_TOKEN",
  "environments": ["staging"],
  "services": {"eks": {"of-api": {
    "display_name": "OF API (Flask)", "ecr_repo": "of-api",
    "helm_repo": "of-helm", "helm_branch": "develop",
    "values_file": "charts/of-api/values-{environment}.yaml", "argocd_app": "of-api-{environment}"
  }}}
}
```

## Run locally

```bash
cp .env.example .env    # git-ignored, MOCK_MODE=true
docker compose up -d --build
```

Open http://localhost:5000 and sign in as `admin` / `admin`, the user that `APP_USER` and `APP_PASSWORD` create on first start. With `MOCK_MODE=true`, S3, ECR, CloudFront, CodeDeploy, GitHub and Argo CD calls return generated data, so you need no cloud credentials; MySQL is real and runs in Compose. `docker compose exec app python -m of_launch.cli users list` shows the users, and `users add`, `delete`, `reset-password` and `set-role` change them. `docker compose down -v` stops both containers and deletes the database.

## Configuration

Every setting is an environment variable, and `.env.example` lists them all with local values. On the host the values come from Secrets Manager at start; anything it leaves out keeps the code default.

| Variables | Purpose | Secret |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `TABLE_NAME_USERS`, `TABLE_NAME_DEPLOYMENTS` | MySQL connection and table names | `DB_PASSWORD` |
| `APP_USER`, `APP_PASSWORD`, `APP_USER_ROLE` | admin created when the users table is empty; default role for `users add` | `APP_PASSWORD` |
| `SEED_USERS` | JSON list of `{"username", "password", "role"}` created at start | yes |
| `APP_SECRET_KEY` | Flask session key | yes |
| `MOCK_MODE`, `FLASK_DEBUG`, `GUNICORN_WORKERS` | fake cloud calls (`true` is the default); Flask dev server instead of gunicorn; gunicorn worker count | no |
| `OF_CLUSTERS_CONFIG_PATH` | registry file, default `config/clusters.json` | no |
| `OF_ARTIFACT_BUCKET`, `OF_WEB_DEPLOY_BUCKET`, `OF_WEB_CLOUDFRONT_ID` | values the registry reads through `${...}` | account values |
| `ARGOCD_OF_URL`, `ARGOCD_OF_TOKEN` | Argo CD API of the `of` cluster | `ARGOCD_OF_TOKEN` |
| `GITHUB_TOKEN`, `OF_GITHUB_OWNER` | token and owner for the Helm values commits | `GITHUB_TOKEN` |
| `OF_SLACK_WEBHOOK_URL` | deploy notifications, off when empty | yes |
| `OF_REGION` | region of the S3, ECR, CloudFront and CodeDeploy calls, default `us-east-1`; the host uses its instance role, no access keys | no |
| `OF_SHARED_EXECUTOR_ENVIRONMENTS`, `OF_DISPLAY_TIMEZONE`, `PER_PAGE_DEFAULT`, `MAX_RECORDS` | `shared-executor` access; history time zone and paging | no |
| `OF_BATCH_STORE_DIR`, `OF_CODEDEPLOY_POLL_INTERVAL_SECONDS`, `OF_CODEDEPLOY_POLL_TIMEOUT_SECONDS`, `OF_DEPLOY_FIRST_SETTLE_SECONDS` | batch deploy state and timing | no |

## Tests

```bash
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD":/app -w /app python:3.11-slim sh -c \
  'pip install -q -r requirements.txt -r requirements-dev.txt && ruff check --no-cache . && pytest -q -p no:cacheprovider'
```

The MySQL tests skip unless `DB_HOST` is set. To run them against the Compose database, add `--network of-launch_app -e DB_HOST=mysql -e DB_PASSWORD=localdevpass`; they create and drop a database named `of_launch_test`.

## How it ships

The host, its image registry and the deployment pipeline are defined outside this repository. That definition commits `.github/workflows/deploy.yml` and `.codedeploy/` here and sets the `OF_LAUNCH_*` Actions secrets they read, so an edit made to those files here is overwritten.

A push to `master` runs the workflow: it builds the image for `linux/arm64` and `linux/amd64`, pushes it tagged with the commit SHA, packages `.codedeploy/` with the image name, and starts a CodeDeploy deployment that restarts the service on the host with the new image.
