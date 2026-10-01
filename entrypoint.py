"""Backward-compatible adapter around the installed CLI; no execution engine."""
import argparse
import os
import re
import runpy
import sys
import time
from urllib.parse import urlparse


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


def publish_result(data):
    status = data['status']
    counts = data.get('counts') or {}
    report_url = safe_report_url(data.get('reportUrl'))
    write_output('test_result', status)
    write_output('run_history_id', data.get('runHistoryId'))
    write_output('report_url', report_url)
    write_output('passed_count', counts.get('passed', 0))
    write_output('failed_count', counts.get('failed', 0))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write(f'## SuperQA execution\n\nResult: **{status}**\n\n')
            summary.write(f"Passed: {counts.get('passed', 0)}; failed: {counts.get('failed', 0)}; "
                          f"blocked: {counts.get('blocked', 0)}; pending: {counts.get('pending', 0)}.\n\n")
            if report_url:
                summary.write(f'[View SuperQA execution]({report_url})\n')


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
    except Exception:
        # Do not echo server responses, notification content, or credentials.
        publish_result({'status': 'failure'})
        print('Unable to complete execution monitoring. Check backend availability and Action configuration.', flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
