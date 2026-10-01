# SuperQA GitHub Action

Execute SuperQA test suites directly in your CI/CD pipeline with seamless integration.

## Features

- ✅ Execute SuperQA test suites in GitHub Actions
- 🔐 Secure API key handling through GitHub Secrets
- 📝 Simple and clean configuration
- 🚀 Fast and lightweight execution

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `api_key` | SuperQA API key (must start with `az-`) | ✅ | - |
| `project_name` | SuperQA project name | ✅ | - |
| `test_plan_name` | Test plan name | ✅ | - |
| `test_run_name` | Deprecated alias for `test_plan_name` | ❌ | - |
| `environment_name` | SuperQA environment (`production`, `staging`, etc.) | ❌ | server `default` |
| `parallel_run` | `true` or `false` | ❌ | `false` |
| `notification_json` | Full notification object (JSON string) | ❌ | test plan default |
| `notification_emails` | Comma-separated failure alert emails | ❌ | - |
| `notify_on_success` | `true` or `false` | ❌ | `false` |
| `skip_notifications` | `true` to disable all alerts | ❌ | `false` |
| `base_url` | SuperQA base URL | ❌ | `https://app.superqa.ai` |

## Outputs

### Optional final-result monitoring

The default remains initiation-only for existing workflows. To wait for actual
test results, enable `wait_for_result` against a backend that provides
`GET /api/execute-now/result/:scheduleId`:

```yaml
- name: Run SuperQA and wait
  uses: superqa-ai/superqa-githubaction@<reviewed-commit-sha>
  timeout-minutes: 35
  with:
    api_key: ${{ secrets.SUPERQA_API_KEY }}
    project_name: MyProject
    test_plan_name: ci-test-plan
    environment_name: staging
    wait_for_result: 'true'
    timeout_seconds: '1800'
    poll_interval_seconds: '5'
```

Waiting returns exit code zero only for a complete passing selection. Failures,
warnings, skipped or blocked coverage, API errors, interruption and timeouts
return nonzero. Older backends fail explicitly in wait mode; the adapter does
not interpret initiation as a passing result. A monitoring timeout does not
cancel the external execution.

Additional inputs are `wait_for_result` (default `false`), `timeout_seconds`
(default `1800`, range 1–86400), and `poll_interval_seconds` (default `5`, range
1–60). Set the GitHub job/step timeout longer than the monitoring deadline.

Wait-mode outputs are `schedule_id`, `run_history_id`, `report_url`,
`passed_count`, `failed_count`, and `test_result` (`passed`, `failed`, `blocked`,
`infrastructure_failed`, `timed_out`, or `failure`). A job summary links to the
execution report. These outputs supplement the legacy `test_result=initiated`.

The result endpoint deliberately blocks schedules with multiple execution
attempts. This Action creates a new immediate schedule for each invocation.

This is the execution foundation for Phase 3. PR synchronization, impact
selection, generated-test approval and the `protect` mode are not yet available.
The existing engine callback authentication also needs hardening before this
is enabled as a required branch-protection check.

| Output | Description |
|--------|-------------|
| `test_result` | `initiated` when execution starts, `failure` on error |

## Usage

### Basic Usage

```yaml
name: SuperQA Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Run SuperQA Tests
        uses: superqa-ai/superqa-githubaction@v1
        with:
          api_key: ${{ secrets.SUPERQA_API_KEY }}
          project_name: 'MyProject'
          test_plan_name: 'ci-test-plan'
```

### Custom Base URL

```yaml
- name: Run SuperQA Tests (Custom URL)
  uses: superqa-ai/superqa-githubaction@v1
  with:
    api_key: ${{ secrets.SUPERQA_API_KEY }}
    project_name: 'MyProject'
    test_plan_name: 'ci-tests'
    base_url: 'https://custom.superqa.ai'
```

### Matrix Strategy for Multiple Test Suites

```yaml
name: Multi-Suite Testing

on:
  push:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        test_suite: ['smoke-tests', 'regression-tests', 'api-tests']
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Run SuperQA Tests - ${{ matrix.test_suite }}
        uses: superqa-ai/superqa-githubaction@v1
        with:
          api_key: ${{ secrets.SUPERQA_API_KEY }}
          project_name: 'MyApp'
          test_plan_name: ${{ matrix.test_suite }}
```

## Setup

### 1. Get Your SuperQA API Key

1. Log in to your SuperQA account
2. Navigate to Account Settings
3. Generate an API key (it will start with `az-`)
4. Copy the API key for use in GitHub Secrets

### 2. Add API Key to GitHub Secrets

1. Go to your repository on GitHub
2. Navigate to Settings > Secrets and variables > Actions
3. Click "New repository secret"
4. Name: `SUPERQA_API_KEY`
5. Value: Your SuperQA API key (starting with `az-`)
6. Click "Add secret"

### 3. Configure Your Workflow

Create a `.github/workflows/superqa.yml` file with your desired configuration using the examples above.

## Troubleshooting

### Common Issues

1. **"API key is required" Error**
   - Ensure you've added `SUPERQA_API_KEY` to your repository secrets
   - Verify the secret name matches exactly

2. **"Invalid API key format" Error**
   - SuperQA API keys must start with `az-`
   - Check that you copied the complete API key

3. **Authentication failed**
   - Verify your API key is active and not expired
   - Check SuperQA account status



## Support

- 📖 [SuperQA Documentation](https://docs.superqa.ai)
- 📧 [Email Support](mailto:support@superqa.ai)
- 🐛 [Report Issues](https://github.com/superqa-ai/superqa-githubaction/issues)

## License

This GitHub Action is released under the [MIT License](LICENSE).

---

**Made with ❤️ by the SuperQA Team**
