import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import json
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('entrypoint', Path(__file__).resolve().parents[1] / 'entrypoint.py')
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)
SCHEDULE = 'a' * 24


def result(status='passed', terminal=True):
    return {'success': True, 'data': {
        'scheduleId': SCHEDULE, 'terminal': terminal, 'status': status,
        'runHistoryId': 'b' * 24,
        'counts': {'total': 1, 'passed': 1, 'failed': 0, 'warning': 0,
                   'skipped': 0, 'blocked': 0, 'pending': 0}
    }}


class Client:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []
        self.timeout = None

    def _make_request(self, method, route):
        self.calls.append((method, route))
        payload = next(self.payloads)
        if isinstance(payload, Exception):
            raise payload
        return types.SimpleNamespace(json=lambda: payload)


class EntrypointTests(unittest.TestCase):
    def test_collects_pull_request_context_from_github_event(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / 'event.json'
            event.write_text(json.dumps({'number': 1847, 'repository': {'full_name': 'company/demo-shop'},
                'pull_request': {'base': {'ref': 'main', 'sha': 'a' * 40},
                                 'head': {'ref': 'feature/payment', 'sha': 'b' * 40}}}))
            with patch.dict(os.environ, {'GITHUB_EVENT_PATH': str(event), 'GITHUB_RUN_ID': '123',
                                         'SUPERQA_PROJECT_NAME': 'Nova SuperQA'}, clear=True):
                context = entrypoint.github_pr_context()
            self.assertEqual(context['repository'], 'company/demo-shop')
            self.assertEqual(context['prNumber'], 1847)
            self.assertEqual(context['headSha'], 'b' * 40)
            self.assertEqual(context['projectName'], 'Nova SuperQA')

    def test_protect_mode_rejects_non_pull_request_event(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / 'event.json'
            event.write_text(json.dumps({'repository': {'full_name': 'company/demo-shop'}}))
            with patch.dict(os.environ, {'GITHUB_EVENT_PATH': str(event)}, clear=True):
                with self.assertRaisesRegex(ValueError, 'pull_request'):
                    entrypoint.github_pr_context()
    def test_waits_after_initiation_until_final_result(self):
        client = Client([result('running', False), result()])
        sleeps = []
        data = entrypoint.poll_result(client, SCHEDULE, 100, 5, clock=lambda: 0, sleep=sleeps.append)
        self.assertEqual(data['status'], 'passed')
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(sleeps, [5])

    def test_terminal_nonpassing_statuses_return_without_turning_green(self):
        for status in ('failed', 'blocked', 'infrastructure_failed'):
            data = entrypoint.poll_result(Client([result(status)]), SCHEDULE, 100, 5, clock=lambda: 0)
            self.assertEqual(data['status'], status)

    def test_unknown_or_incomplete_results_fail_closed(self):
        for payload in (result('initiated'), result()):
            if payload['data']['status'] == 'passed':
                payload['data']['counts']['pending'] = 1
            with self.assertRaises(ValueError):
                entrypoint.poll_result(Client([payload]), SCHEDULE, 100, 5, clock=lambda: 0)

    def test_rejects_old_backend_or_wrong_execution(self):
        for payload in ({'success': True, 'data': {'status': 'success'}}, result()):
            if 'terminal' in payload['data']:
                payload['data']['scheduleId'] = 'c' * 24
            with self.assertRaises(ValueError):
                entrypoint.poll_result(Client([payload]), SCHEDULE, 100, 5, clock=lambda: 0)

    def test_deadline_is_not_a_pass(self):
        data = entrypoint.poll_result(Client([]), SCHEDULE, 10, 5, clock=lambda: 10)
        self.assertEqual(data['status'], 'timed_out')

    def test_transient_wrapped_api_errors_retry_but_auth_does_not(self):
        APIError = type('APIError', (Exception,), {})
        sleeps = []
        data = entrypoint.poll_result(Client([APIError('API Error (503): unavailable'), result()]),
                                     SCHEDULE, 100, 5, clock=lambda: 0, sleep=sleeps.append)
        self.assertEqual(data['status'], 'passed')
        self.assertEqual(sleeps, [5])
        with self.assertRaises(APIError):
            entrypoint.poll_result(Client([APIError('API Error (403): denied')]),
                                   SCHEDULE, 100, 5, clock=lambda: 0)

    def test_default_delegates_unchanged_to_installed_cli(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'argv',
                ['entrypoint.py', '-m', 'superqa.cli', '--project-name', 'Example']), \
                patch.object(entrypoint.runpy, 'run_module') as run:
            self.assertEqual(entrypoint.main(), 0)
            run.assert_called_once_with('superqa.cli', run_name='__main__')
            self.assertEqual(sys.argv, ['superqa.cli', '--project-name', 'Example'])

    def test_monitoring_interrupt_is_nonzero(self):
        with patch.dict(os.environ, {'SUPERQA_WAIT_FOR_RESULT': 'true'}, clear=True), \
                patch.object(entrypoint, 'run_wait_mode', side_effect=KeyboardInterrupt), \
                patch.object(entrypoint, 'publish_result') as publish:
            self.assertEqual(entrypoint.main(), 1)
            publish.assert_called_once_with({'status': 'failure'})

    def test_wait_mode_creates_one_execution_and_returns_final_exit_code(self):
        for status, expected_exit in [('passed', 0), ('failed', 1), ('blocked', 1)]:
            client = Client([result(status)])
            calls = []
            client.execute_now = lambda **kwargs: (calls.append(kwargs) or
                types.SimpleNamespace(success=True, data={'scheduleId': SCHEDULE}))
            client_module = types.ModuleType('superqa.client')
            client_module.SuperQAClient = lambda **kwargs: client
            cli_module = types.ModuleType('superqa.cli')
            cli_module.build_notification_payload = lambda **kwargs: kwargs
            modules = {'superqa': types.ModuleType('superqa'), 'superqa.client': client_module, 'superqa.cli': cli_module}
            with patch.dict(sys.modules, modules), patch.dict(os.environ, {
                    'SUPERQA_WAIT_FOR_RESULT': 'true', 'SUPERQA_API_KEY': 'az-unit-test',
                    'SUPERQA_ENVIRONMENT_NAME': 'staging', 'SUPERQA_PARALLEL_RUN': 'true'
                }, clear=True), patch.object(sys, 'argv', ['entrypoint.py', '-m', 'superqa.cli',
                    '--project-name', 'Example', '--test-plan-name', 'Regression']), \
                    patch.object(entrypoint, 'write_output') as write:
                self.assertEqual(entrypoint.main(), expected_exit)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['environment_name'], 'staging')
                self.assertEqual(calls[0]['parallel_run'], True)
                write.assert_any_call('test_result', status)

    def test_outputs_and_summary_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            summary = Path(directory) / 'summary'
            with patch.dict(os.environ, {'GITHUB_OUTPUT': str(output), 'GITHUB_STEP_SUMMARY': str(summary)}, clear=True):
                data = result()['data']
                data['reportUrl'] = 'https://app.superqa.ai/executions/example/test-results'
                entrypoint.publish_result(data)
                self.assertIn('test_result=passed\n', output.read_text())
                self.assertIn('failed_count=0\n', output.read_text())
                self.assertIn('View SuperQA execution', summary.read_text())
                with self.assertRaises(ValueError):
                    entrypoint.write_output('test_result', 'passed\nforged=true')
                self.assertEqual(entrypoint.safe_report_url('javascript:alert(1)'), '')

    def test_release_decision_outputs_are_published(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            with patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}, clear=True):
                data = result()['data']
                data['releaseDecision'] = {
                    'recommendation': 'SHIP', 'confidenceScore': 100, 'policyVersion': '1.0'
                }
                entrypoint.publish_result(data)
            self.assertIn('release_decision=SHIP\n', output.read_text())
            self.assertIn('confidence_score=100\n', output.read_text())

    def test_backend_error_is_safe_for_logs_and_outputs(self):
        self.assertEqual(
            entrypoint.safe_error_message('Execution failed\r\n::set-output name=x::forged\x00'),
            'Execution failed ::set-output name=x::forged'
        )
        self.assertEqual(len(entrypoint.safe_error_message('x' * 600)), 500)
        self.assertNotIn('az-secret', entrypoint.safe_error_message('api_key=az-secret'))

    def test_http_error_exposes_sanitized_backend_diagnostic(self):
        response = types.SimpleNamespace(
            status_code=409,
            json=lambda: {'error': 'Project mismatch token=secret-value'}
        )
        error = entrypoint.requests.HTTPError('raw response')
        error.response = response
        message = entrypoint.safe_exception_message(error)
        self.assertEqual(message, 'Backend HTTP 409: Project mismatch token=[REDACTED]')


if __name__ == '__main__':
    unittest.main()
