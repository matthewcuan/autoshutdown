# autoshutdown

AWS Lambda function that monitors one EC2 instance for active SSH sessions and stops it after repeated idle checks.

## How it works

- Checks EC2 instance state.
- Uses AWS Systems Manager (SSM) to detect established SSH connections on port `22`.
- Tracks consecutive idle checks in DynamoDB.
- Stops the instance after `IDLE_THRESHOLD` idle runs.
- Honors `ALLOW_STOP` safety switch.

## Required environment variables

- `INSTANCE_ID`: EC2 instance ID to monitor.
- `STATE_TABLE`: DynamoDB table name used for idle counter state.
- `IDLE_THRESHOLD` (optional): idle check count before stop. Default: `3`.
- `ALLOW_STOP` (optional): set to `true` to allow stop action. Default: `false`.
- `SSM_MAX_WAIT_SECONDS` (optional): max seconds to wait for SSM command result. Default: `15`.
- `SSM_POLL_INTERVAL_SECONDS` (optional): polling interval while waiting for SSM. Default: `0.5`.

## Local testing

```bash
python -m pip install --upgrade pip
pip install pytest
pytest -q
```

## CI/CD

GitHub Actions workflow is in `.github/workflows/deploy.yml`.

- Pull requests run tests.
- Push to `main` runs tests, then deploys Lambda if tests pass.
