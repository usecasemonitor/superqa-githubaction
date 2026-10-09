# SuperQA GitHub Action

Run SuperQA test plans and pull-request protection checks in GitHub Actions.

## Security

- Store the SuperQA API key in GitHub Actions secrets. Never commit it to a workflow or repository.
- Pin this Action to a reviewed release tag or, for the strongest supply-chain control, a full commit SHA.
- Grant workflows only `contents: read` and `pull-requests: read` unless other steps require broader permissions.
- Do not use `pull_request_target` to expose secrets to untrusted pull-request code. GitHub normally withholds repository secrets from fork pull requests.

## Inputs

| Input | Required | Default | Description |
|---|---:|---|---|
| `api_key` | Yes | — | SuperQA API key, supplied through a GitHub secret |
| `mode` | No | `run-plan` | `run-plan` or `protect` |
| `project_name` | No | — | Project name; `project_id` is preferred when available |
| `project_id` | No | — | Immutable SuperQA project ID |
| `test_plan_name` | No | — | Test plan name for `run-plan` mode |
| `test_run_name` | No | — | Deprecated alias for `test_plan_name` |
| `environment_name` | No | Server default | Execution environment, such as `staging` |
| `parallel_run` | No | `false` | Run selected tests in parallel |
| `wait_for_result` | No | `false` | Wait for a reconciled final result |
| `timeout_seconds` | No | `1800` | Result deadline, from 1 to 86400 seconds |
| `poll_interval_seconds` | No | `5` | Poll interval, from 1 to 60 seconds |
| `notification_json` | No | Plan default | Notification configuration as a JSON string |
| `notification_emails` | No | — | Comma-separated failure-alert recipients |
| `notify_on_success` | No | `false` | Also send success notifications |
| `skip_notifications` | No | `false` | Disable execution notifications |
| `base_url` | No | `https://app.superqa.ai` | SuperQA service URL |

## Run a test plan

Add `SUPERQA_API_KEY` under **Settings > Secrets and variables > Actions**, then create `.github/workflows/superqa.yml`:

```yaml
name: SuperQA Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 35
    steps:
      - name: Run SuperQA and wait for the result
        uses: superqa-ai/superqa-githubaction@v1
        with:
          api_key: ${{ secrets.SUPERQA_API_KEY }}
          project_name: MyProject
          test_plan_name: ci-test-plan
          environment_name: staging
          wait_for_result: 'true'
          timeout_seconds: '1800'
          poll_interval_seconds: '5'
```

With `wait_for_result: 'false'`, the Action exits after SuperQA accepts the execution and reports `test_result=initiated`. With waiting enabled, it exits successfully only when the complete selected test set passes. Test failures, blocked or incomplete coverage, infrastructure failures, API errors, interruptions, and timeouts fail the Action. A monitoring timeout does not cancel the execution in SuperQA.

## Protect a pull request

Connect the GitHub repository to the intended project in SuperQA, then use:

```yaml
name: SuperQA Protect

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: read

jobs:
  protect:
    runs-on: ubuntu-latest
    timeout-minutes: 35
    steps:
      - name: Analyze changes and run affected tests
        uses: superqa-ai/superqa-githubaction@v1
        with:
          api_key: ${{ secrets.SUPERQA_API_KEY }}
          project_id: ${{ vars.SUPERQA_PROJECT_ID }}
          mode: protect
          wait_for_result: 'true'
          timeout_seconds: '1800'
```

The Action reads pull-request metadata from GitHub's event file. SuperQA uses the repository-scoped connection configured for the project, so the workflow does not need to check out source code or pass a GitHub token to this Action. When no existing test covers a verified PR impact, SuperQA automatically derives the affected feature from the PR and project knowledge, skips cases that need test data or typed user input, generates autonomous alternatives, and runs validated low- or medium-risk cases. High-risk actions remain blocked or require review.

## Outputs

| Output | Description |
|---|---|
| `test_result` | Final or initiation status, depending on mode |
| `schedule_id` | Immediate-execution schedule ID |
| `run_history_id` | Final execution history ID |
| `report_url` | Validated HTTPS execution-report URL |
| `passed_count` / `failed_count` | Final test counts |
| `protect_run_id` | Protect run ID |
| `protect_outcome` | Structured Protect outcome code |
| `protect_implementation_version` | Protect implementation identifier reported by SuperQA |
| `test_run_id` | Protect execution history ID |
| `passed_tests` / `failed_tests` | Protect test counts |
| `release_decision` | `SHIP`, `REVIEW`, or `BLOCK` |
| `confidence_score` | Release-policy confidence score from 0 to 100 |
| `confidence` | Alias for `confidence_score` |
| `risk_level` | Reported release risk level |
| `review_required` | Whether manual review is required |
| `tests_executed` | Number of tests executed |
| `tests_passed` / `tests_failed` | Detailed result counts |
| `tests_generated` | Number of test cases generated automatically for uncovered Protect impact |
| `test_results_url` | Protect test-results URL, when available |
| `error_message` | Sanitized diagnostic when execution fails |

## Use outputs

```yaml
- name: Run SuperQA
  id: superqa
  uses: superqa-ai/superqa-githubaction@v1
  with:
    api_key: ${{ secrets.SUPERQA_API_KEY }}
    project_id: ${{ vars.SUPERQA_PROJECT_ID }}
    test_plan_name: ci-test-plan
    wait_for_result: 'true'

- name: Show report
  if: always() && steps.superqa.outputs.report_url != ''
  run: echo "Report: ${{ steps.superqa.outputs.report_url }}"
```

Treat outputs as untrusted data if passing them to a shell. Prefer direct workflow expressions and avoid evaluating output text as commands.

## Troubleshooting

- **API key rejected:** confirm the `SUPERQA_API_KEY` secret contains the full, active key and is available to this workflow event.
- **Project or plan not found:** verify the supplied ID or exact name and the API key's account access.
- **Protect requires a pull request:** run Protect only for a `pull_request` event and ensure the repository is connected to the SuperQA project.
- **Monitoring timed out:** set the step or job timeout higher than `timeout_seconds`; the remote execution may continue after monitoring ends.
- **Fork pull request skipped or rejected:** repository secrets are normally unavailable to workflows triggered from forks.

## Support

- [SuperQA documentation](https://docs.superqa.ai)
- [Email support](mailto:support@superqa.ai)
- [Report an Action issue](https://github.com/superqa-ai/superqa-githubaction/issues)
