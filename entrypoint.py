"""Backward-compatible adapter around the installed CLI; no execution engine."""
import argparse
import json
import os
import re
import runpy
import sys
import time
from urllib.parse import urlparse

import requests


def write_output(name, value):
    value = '' if value is None else str(value)
    if '\n' in value or '\r' in value:
        raise ValueError('Invalid multiline output')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write(f'{name}={value}\n')


def boolean_env(name):
    value = os.environ.get(name, 'false').strip().lower()
    if value not in ('true', 'false'):
        raise ValueError(f'{name} must be true or false')
    return value == 'true'


def integer_env(name, default, minimum, maximum):
    value = int(os.environ.get(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return value


def safe_report_url(value):
    value = str(value or '')
    parsed = urlparse(value)
    return value if (parsed.scheme in ('http', 'https') and parsed.netloc
                     and not re.search(r'[\s<>\[\]()]', value)) else ''


def safe_error_message(value):
    """Make a backend diagnostic safe for a single GitHub output/log line."""
    message = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(value or '')).strip()
    message = re.sub(r'(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;]+', r'\1[REDACTED]', message)
    message = re.sub(r'(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+', r'\1[REDACTED]', message)
    message = re.sub(r'(?i)\baz-[a-z0-9._-]+\b', '[REDACTED]', message)
    return message[:500]


def safe_exception_message(error):
    """Expose actionable HTTP/configuration context without echoing credentials."""
    response = getattr(error, 'response', None)
    if response is not None:
        status = getattr(response, 'status_code', None)
        detail = ''
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get('error') or payload.get('message') or ''
        except (ValueError, TypeError):
            detail = ''
        prefix = f'Backend HTTP {status}' if status else 'Backend request failed'
        return safe_error_message(f'{prefix}: {detail}' if detail else prefix)
    if isinstance(error, (ValueError, requests.RequestException)):
        return safe_error_message(error)
    return 'Unexpected Action error. Review the backend and Action logs.'


def protect_blocking_reasons(data):
    """Return safe diagnostics without allowing report payload shape to fail the Action."""
    if not isinstance(data, dict):
        return []
    reasons = []
    gaps = data.get('coverageGaps')
    if isinstance(gaps, list):
        reasons.extend(gaps)
    decision = data.get('releaseDecision')
    if isinstance(decision, dict) and isinstance(decision.get('reasons'), list):
        reasons.extend(decision['reasons'])
    resolution = data.get('testDataResolution')
    blocked_items = resolution.get('blockedReasons') if isinstance(resolution, dict) else []
    if isinstance(blocked_items, list):
        for blocked in blocked_items:
            if isinstance(blocked, dict) and isinstance(blocked.get('reasons'), list):
                reasons.extend(blocked['reasons'])
            elif isinstance(blocked, str):
                reasons.append(blocked)
    return list(dict.fromkeys(safe_error_message(reason) for reason in reasons if reason))[:10]


def publish_result(data):
    status = data['status']
    counts = data.get('counts') or {}
    report_url = safe_report_url(data.get('reportUrl'))
    write_output('test_result', status)
    write_output('run_history_id', data.get('runHistoryId'))
    write_output('report_url', report_url)
    write_output('passed_count', counts.get('passed', 0))
    write_output('failed_count', counts.get('failed', 0))
    decision = data.get('releaseDecision') or {}
    write_output('release_decision', decision.get('recommendation', ''))
    write_output('confidence_score', decision.get('confidenceScore', ''))
    write_output('confidence', decision.get('confidenceScore', ''))
    risk = data.get('riskAssessment') or {}
    write_output('risk_level', risk.get('level', decision.get('riskLevel', '')))
    write_output('review_required', str(bool(data.get('reviewRequired', decision.get('reviewRequired', False)))).lower())
    write_output('tests_executed', counts.get('executed', counts.get('total', 0)))
    write_output('tests_passed', counts.get('passed', 0))
    write_output('tests_failed', counts.get('failed', 0))
    write_output('tests_generated', counts.get('generated', 0))
    blocking_reasons = protect_blocking_reasons(data)
    if blocking_reasons:
        print(f"SuperQA Protect blocked: {'; '.join(blocking_reasons)}", flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write(f'## SuperQA execution\n\nResult: **{status}**\n\n')
            summary.write(f"Passed: {counts.get('passed', 0)}; failed: {counts.get('failed', 0)}; "
                          f"blocked: {counts.get('blocked', 0)}; pending: {counts.get('pending', 0)}.\n\n")
            if report_url:
                summary.write(f'[View SuperQA execution]({report_url})\n')


def github_pr_context():
    event_path = os.environ.get('GITHUB_EVENT_PATH', '')
    if not event_path:
        raise ValueError('GITHUB_EVENT_PATH is unavailable')
    with open(event_path, encoding='utf-8') as event_file:
        event = json.load(event_file)
    pull_request = event.get('pull_request') or {}
    repository = (event.get('repository') or {}).get('full_name') or os.environ.get('GITHUB_REPOSITORY')
    number = event.get('number')
    base = pull_request.get('base') or {}
    head = pull_request.get('head') or {}
    if not repository or not isinstance(number, int) or not base.get('sha') or not head.get('sha'):
        raise ValueError('Protect mode requires a pull_request event')
    workflow_run_id = os.environ.get('GITHUB_RUN_ID', '')
    workflow_attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    return {
        'repository': repository,
        'projectId': os.environ.get('SUPERQA_PROJECT_ID', '').strip(),
        'projectName': os.environ.get('SUPERQA_PROJECT_NAME', '').strip(),
        'prNumber': number,
        'baseBranch': (base.get('ref') or '')[:500], 'headBranch': (head.get('ref') or '')[:500],
        'baseSha': base['sha'], 'headSha': head['sha'],
        'workflowRunId': f'{workflow_run_id}:{workflow_attempt}' if workflow_run_id else ''
    }


def run_protect_mode(clock=time.monotonic, sleep=time.sleep):
    api_key = os.environ.get('SUPERQA_API_KEY', '')
    if not api_key.startswith('az-'):
        raise ValueError('Valid SuperQA API key required')
    base_url = os.environ.get('SUPERQA_BASE_URL', 'https://app.superqa.ai').rstrip('/')
    parsed = urlparse(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('Invalid SuperQA base URL')
    timeout = integer_env('SUPERQA_RESULT_TIMEOUT_SECONDS', 1800, 1, 86400)
    interval = integer_env('SUPERQA_POLL_INTERVAL_SECONDS', 5, 1, 60)
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    context = github_pr_context()
    response = requests.post(f'{base_url}/api/protect/runs', headers=headers,
                             json=context, timeout=min(30, timeout))
    response.raise_for_status()
    payload = response.json()
    run_id = str((payload.get('data') or {}).get('protectRunId') or '')
    if not re.fullmatch(r'[a-fA-F0-9]{24}', run_id):
        raise ValueError('Backend did not return a valid Protect run')
    write_output('protect_run_id', run_id)
    deadline = clock() + timeout
    data = None
    while clock() < deadline:
        result = requests.get(f'{base_url}/api/protect/runs/{run_id}', headers=headers,
                              timeout=max(0.1, min(30, deadline - clock())))
        result.raise_for_status()
        data = (result.json().get('data') or {})
        if data.get('protectRunId') != run_id or data.get('commitSha') != context['headSha']:
            raise ValueError('Protect result does not belong to this commit')
        if data.get('terminal') is True:
            break
        sleep(min(interval, max(0, deadline - clock())))
    else:
        data = {'result': 'timed_out', 'status': 'timed_out', 'counts': {}}
    counts = data.get('counts') or {}
    result_name = data.get('result') or 'execution_error'
    error_message = safe_error_message(data.get('error'))
    decision = data.get('releaseDecision') or {}
    recommendation = decision.get('recommendation') or ''
    write_output('test_result', result_name)
    write_output('protect_outcome', data.get('outcomeCode') or result_name.upper())
    write_output('error_message', error_message)
    write_output('test_run_id', data.get('testRunId'))
    write_output('run_history_id', data.get('testRunId'))
    write_output('report_url', safe_report_url(data.get('reportUrl')))
    write_output('passed_tests', counts.get('passed', 0))
    write_output('failed_tests', counts.get('failed', 0))
    write_output('passed_count', counts.get('passed', 0))
    write_output('failed_count', counts.get('failed', 0))
    write_output('release_decision', recommendation)
    write_output('confidence_score', decision.get('confidenceScore', ''))
    write_output('confidence', decision.get('confidenceScore', ''))
    risk = data.get('riskAssessment') or {}
    write_output('risk_level', risk.get('level', decision.get('riskLevel', '')))
    write_output('review_required', str(bool(data.get('reviewRequired', decision.get('reviewRequired', False)))).lower())
    write_output('tests_executed', counts.get('executed', counts.get('total', 0)))
    write_output('tests_passed', counts.get('passed', 0))
    write_output('tests_failed', counts.get('failed', 0))
    write_output('tests_generated', counts.get('generated', 0))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write(f"## SuperQA Protect\n\nPR: **#{data.get('prNumber', '')}**  \n")
            summary.write(f"Commit: `{str(data.get('commitSha', ''))[:12]}`  \nResult: **{result_name}**\n")
            if recommendation:
                summary.write(f"Release decision: **{safe_error_message(recommendation)}**  \n")
                summary.write(f"Policy: `{safe_error_message(decision.get('policyVersion', ''))}`; confidence: **{decision.get('confidenceScore', '')}**\n\n")
            features = ', '.join(data.get('affectedFeatures') or []) or 'Review required'
            summary.write(f"Affected features: {features}\n\nPassed: {counts.get('passed', 0)}; failed: {counts.get('failed', 0)}.\n\n")
            if blocking_reasons:
                summary.write('Blocking reasons:\n' + ''.join(f'- {reason}\n' for reason in blocking_reasons) + '\n')
            report_url = safe_report_url(data.get('reportUrl'))
            if report_url:
                summary.write(f'[View SuperQA release report]({report_url})\n')
    if result_name == 'execution_error':
        detail = error_message or 'The backend did not provide an error message.'
        print(f'SuperQA Protect execution error: {detail}', flush=True)
    return 0 if result_name == 'passed' and recommendation in ('', 'PASS', 'SHIP') else 1


def poll_result(client, schedule_id, deadline, interval, clock=time.monotonic, sleep=time.sleep):
    failures = 0
    while clock() < deadline:
        client.timeout = max(0.1, min(30, deadline - clock()))
        try:
            response = client._make_request('GET', f'/api/execute-now/result/{schedule_id}')
            payload = response.json()
            data = payload.get('data', {})
            if payload.get('success') is not True or not isinstance(data.get('terminal'), bool):
                raise ValueError('Backend does not support reconciled execution results')
            if str(data.get('scheduleId')) != schedule_id:
                raise ValueError('Result belongs to a different execution')
            failures = 0
        except Exception as error:
            # Retry only transient network, rate-limit and upstream failures.
            status_code = getattr(getattr(error, 'response', None), 'status_code', None)
            transient = (status_code in (429, 502, 503, 504)
                         or type(error).__name__ in ('ConnectionError', 'Timeout'))
            # The existing client wraps requests errors. Explicitly recognize
            # its bounded timeout/connection messages, not arbitrary API errors.
            transient = transient or (type(error).__name__ == 'SuperQAError'
                                      and str(error).startswith(('Request timed out', 'Failed to connect')))
            transient = transient or (type(error).__name__ == 'APIError'
                                      and bool(re.match(r'^API Error \((429|502|503|504)\):', str(error))))
            if not transient or failures >= 3:
                raise
            failures += 1
            sleep(min(interval * failures, max(0, deadline - clock())))
            continue
        if clock() >= deadline:
            break
        if data['terminal']:
            if data.get('status') not in ('passed', 'failed', 'blocked', 'infrastructure_failed'):
                raise ValueError('Unknown terminal execution status')
            counts = data.get('counts') or {}
            if data['status'] == 'passed' and not (
                isinstance(counts.get('total'), int) and counts['total'] > 0
                and counts.get('passed') == counts['total']
                and all(counts.get(key) == 0 for key in ('failed', 'warning', 'skipped', 'blocked', 'pending'))
            ):
                raise ValueError('Incomplete execution cannot pass')
            return data
        sleep(min(interval, max(0, deadline - clock())))
    return {'terminal': True, 'status': 'timed_out', 'scheduleId': schedule_id}


def run_wait_mode(arguments):
    from superqa.client import SuperQAClient
    from superqa.cli import build_notification_payload

    parser = argparse.ArgumentParser(description='SuperQA final-result mode')
    parser.add_argument('--project-name', '-p')
    parser.add_argument('--test-plan-name')
    parser.add_argument('--test-run-name', '-t')
    parser.add_argument('--project-id')
    parser.add_argument('--test-plan-id')
    parser.add_argument('--test-run-id')
    parser.add_argument('--api-key')
    parser.add_argument('--base-url', default=os.environ.get('SUPERQA_BASE_URL', 'https://app.superqa.ai'))
    parser.add_argument('--environment-name', '-e')
    parser.add_argument('--parallel-run', action='store_true')
    parser.add_argument('--notification-json')
    parser.add_argument('--notification-emails')
    parser.add_argument('--notify-on-success', action='store_true')
    parser.add_argument('--skip-notifications', action='store_true')
    options = parser.parse_args(arguments)
    api_key = options.api_key or os.environ.get('SUPERQA_API_KEY', '')
    if not api_key.startswith('az-'):
        raise ValueError('Valid SuperQA API key required')
    timeout = integer_env('SUPERQA_RESULT_TIMEOUT_SECONDS', 1800, 1, 86400)
    interval = integer_env('SUPERQA_POLL_INTERVAL_SECONDS', 5, 1, 60)
    deadline = time.monotonic() + timeout
    client = SuperQAClient(api_key=api_key, base_url=options.base_url, timeout=min(30, timeout))
    notification = build_notification_payload(
        notification_json=options.notification_json or os.environ.get('SUPERQA_NOTIFICATION_JSON'),
        notification_emails=options.notification_emails or os.environ.get('SUPERQA_NOTIFICATION_EMAILS'),
        notify_on_success=options.notify_on_success or boolean_env('SUPERQA_NOTIFY_ON_SUCCESS'),
        skip_notifications=options.skip_notifications or boolean_env('SUPERQA_SKIP_NOTIFICATIONS'),
    )
    response = client.execute_now(
        project_name=options.project_name,
        test_plan_name=options.test_plan_name or options.test_run_name,
        project_id=options.project_id,
        test_plan_id=options.test_plan_id or options.test_run_id,
        environment_name=options.environment_name or os.environ.get('SUPERQA_ENVIRONMENT_NAME') or None,
        parallel_run=options.parallel_run or boolean_env('SUPERQA_PARALLEL_RUN'),
        notification=notification,
    )
    schedule_id = str(response.data.get('scheduleId', ''))
    if response.success is not True or not re.fullmatch(r'[a-fA-F0-9]{24}', schedule_id):
        raise ValueError('Backend did not return a valid execution')
    write_output('schedule_id', schedule_id)
    print(f'Execution {schedule_id} initiated; waiting for final result.', flush=True)
    data = poll_result(client, schedule_id, deadline, interval)
    publish_result(data)
    print(f"Execution result: {data['status']}", flush=True)
    return 0 if data['status'] == 'passed' else 1


def main():
    arguments = sys.argv[1:]
    if arguments[:2] == ['-m', 'superqa.cli']:
        arguments = arguments[2:]
    try:
        mode = os.environ.get('SUPERQA_MODE', 'run-plan').strip().lower()
        if mode not in ('run-plan', 'protect'):
            raise ValueError('SUPERQA_MODE must be run-plan or protect')
        if mode == 'protect':
            return run_protect_mode()
        if not boolean_env('SUPERQA_WAIT_FOR_RESULT'):
            # Preserve installed CLI options, output and initiation-only behavior.
            sys.argv = ['superqa.cli', *arguments]
            runpy.run_module('superqa.cli', run_name='__main__')
            return 0
        return run_wait_mode(arguments)
    except KeyboardInterrupt:
        publish_result({'status': 'failure'})
        print('Execution monitoring interrupted.', flush=True)
        return 1
    except Exception as error:
        detail = safe_exception_message(error)
        publish_result({'status': 'failure'})
        write_output('error_message', detail)
        print(f'Unable to complete execution monitoring: {detail}', flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
