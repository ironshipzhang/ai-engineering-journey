"""E2c orchestration tests; local fixtures, fake configuration, simulated transport."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import dashscope_embedding as embedding
import json_retrieval as retrieval
import live_query_retrieval as live
import prepare_corpus as corpus

ENDPOINT = 'https://ws-test.cn-beijing.maas.aliyuncs.com' + embedding.API_PATH
KEY = 'fake-e2c-secret'
QUESTION = '  迁移部分执行时怎么办？\n'


def payload():
    return {'request_id': 'test-e2c-request', 'usage': {'total_tokens': 17},
            'output': {'embeddings': [{'text_index': 0, 'embedding': [1.0] * 64}]}}


def reply(value=None, status=200):
    return embedding.Reply(status, json.dumps(payload() if value is None else value).encode())


class LiveQueryRetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.knowledge = self.root / 'knowledge'
        shutil.copytree(corpus.DEFAULT_KNOWLEDGE, self.knowledge)
        self.prepared = self.root / 'prepared'
        manifest = corpus.prepare(self.knowledge, self.prepared)
        chunks = retrieval.read_json(self.prepared / 'corpus/chunks.json')
        self.config = self.root / 'fake.toml'
        self.config_text = ('[embedding]\nprovider="dashscope"\nmodel="text-embedding-v4"\n'
                            f'api_key="{KEY}"\nendpoint="{ENDPOINT}"\ndimension=64\n')
        self.config.write_text(self.config_text)
        self.contract = retrieval.encoding_contract(embedding.EmbeddingConfig(ENDPOINT, KEY, 64).public())
        self.body = {'artifact_type': retrieval.ARTIFACT_TYPE, 'format_version': 1,
                     'e1_build_id': manifest['build_id'], 'encoding': self.contract,
                     'provenance': {'fixture': 'synthetic vectors, no semantic evaluation'},
                     'documents': [{**c, 'vector': [i + 1.0] + [1.0] * 63} for i, c in enumerate(chunks)]}
        self.artifact = self.root / 'vectors.json'
        self.artifact.write_bytes(corpus.json_bytes(retrieval.seal(self.body)))
        self.counter = 0
        self.original_read = embedding.read_embedding_config
        def fake_config_only(path, endpoint=None):
            self.assertEqual(path, self.config)
            return self.original_read(path, endpoint)
        self.read_config = self.patch(embedding, 'read_embedding_config', side_effect=fake_config_only)
        self.request = self.patch(embedding, 'request_embeddings', return_value=reply())
        self.network = self.patch(embedding, 'build_opener', side_effect=AssertionError('No real network'))
        self.build = self.patch(retrieval, 'build', side_effect=AssertionError('No document build'))
        self.prepare = self.patch(corpus, 'prepare', side_effect=AssertionError('No document preparation'))
        self.addCleanup(self.build.assert_not_called)
        self.addCleanup(self.prepare.assert_not_called)

    def patch(self, target, name, **kwargs):
        patcher = patch.object(target, name, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def run_query(self, **kwargs):
        self.counter += 1
        options = dict(question=QUESTION, prepared=self.prepared, artifact_path=self.artifact,
                       output=self.root / f'run-{self.counter}.json', config_path=self.config,
                       knowledge=self.knowledge)
        options.update(kwargs)
        result = live.run_query(**options)
        self.assertEqual(json.loads(options['output'].read_text()), result)
        self.assertNotIn(KEY, options['output'].read_text())
        return result

    def assert_precheck_failure(self, result, stage):
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error']['stage'], stage)
        self.assertEqual(result['http_attempts'], 0)
        self.assertEqual(result['usage'], {'known_total_tokens': 0, 'complete': True})
        self.assertIsNone(result['retrieval'])
        self.request.assert_not_called()

    def test_success_one_query_preserves_text_and_matches_checked_search(self):
        before = self.artifact.read_bytes()
        output = self.root / 'reserved.json'
        def config_after_reservation(path, endpoint=None):
            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes(), b'')
            return self.original_read(path, endpoint)
        self.read_config.side_effect = config_after_reservation
        with patch.object(retrieval, 'search', wraps=retrieval.search) as search:
            result = self.run_query(output=output)
            search.assert_called_once()
        self.assertEqual(result['status'], 'succeeded')
        self.request.assert_called_once()
        self.assertEqual(self.request.call_args.args[1:], ([QUESTION], 'query'))
        self.assertEqual(result['question'], QUESTION)
        self.assertEqual(result['query']['text'], QUESTION)
        self.assertEqual(result['http_attempts'], 1)
        self.assertEqual(result['usage'], {'known_total_tokens': 17, 'complete': True})
        expected = retrieval.search(retrieval.read_json(self.artifact), result['query'], self.contract,
                                    3, prepared=self.prepared, knowledge=self.knowledge)
        self.assertEqual(result['retrieval'], expected)
        self.assertEqual(result['retrieval']['evidence_status'], 'candidates_only')
        self.assertEqual(self.artifact.read_bytes(), before)
        self.assertNotIn('documents', result)
        self.network.assert_not_called()

    def test_invalid_questions_fail_before_configuration_including_unicode(self):
        for question in ('', ' \n ', '中' * 3000, '\ud800', None, 123):
            with self.subTest(question=repr(question)[:40]):
                self.assert_precheck_failure(self.run_query(question=question), 'input_validation')
        self.read_config.assert_not_called()

    def test_top_k_invalid_types_fail_before_request(self):
        for top_k in (0, -1, True, '3', 1.5, float('nan')):
            self.assert_precheck_failure(self.run_query(top_k=top_k), 'input_validation')
        self.read_config.assert_not_called()

    def test_output_existing_missing_parent_and_symlink_prevent_config_and_requests(self):
        existing = self.root / 'existing.json'
        existing.write_text('keep')
        dangling = self.root / 'link.json'
        dangling.symlink_to(self.root / 'missing-target')
        for output in (existing, self.root / 'absent/result.json', dangling, self.root):
            with self.assertRaises(live.OutputError) as error:
                self.run_query(output=output)
            self.assertEqual(error.exception.result['http_attempts'], 0)
        self.assertEqual(existing.read_text(), 'keep')
        self.read_config.assert_not_called()
        self.request.assert_not_called()

    def test_output_permission_failure_safe(self):
        with patch.object(Path, 'open', side_effect=PermissionError(KEY)):
            with self.assertRaises(live.OutputError) as error:
                self.run_query()
        self.assertNotIn(KEY, str(error.exception))
        self.read_config.assert_not_called()
        self.request.assert_not_called()

    def test_stale_sources_fail_before_configuration(self):
        path = self.knowledge / 'migration-guide.md'
        path.write_text(path.read_text() + '\n变化\n')
        self.assert_precheck_failure(self.run_query(), 'artifact_check')
        self.read_config.assert_not_called()

    def test_artifact_corruption_source_and_build_mismatch_fail_before_configuration(self):
        originals = self.artifact.read_bytes()
        for change in ('corrupt', 'source', 'build', 'missing'):
            if change == 'corrupt': self.artifact.write_text('{')
            elif change == 'missing': self.artifact.unlink()
            else:
                body = deepcopy(self.body)
                if change == 'source': body['documents'][0]['source']['start_line'] += 1
                else: body['e1_build_id'] = 'wrong'
                self.artifact.write_bytes(corpus.json_bytes(retrieval.seal(body)))
            self.assert_precheck_failure(self.run_query(), 'artifact_check')
            self.artifact.write_bytes(originals)
        self.read_config.assert_not_called()

    def test_invalid_config_fails_without_request_and_secret_echo(self):
        for content in ('[broken', self.config_text.replace(KEY, ''),
                        self.config_text.replace('dashscope', 'other'),
                        self.config_text.replace('text-embedding-v4', 'other'),
                        self.config_text.replace('dimension=64', 'dimension=true')):
            self.config.write_text(content)
            self.assert_precheck_failure(self.run_query(), 'configuration')
        self.config.unlink()
        self.assert_precheck_failure(self.run_query(), 'configuration')

    def test_dimension_endpoint_and_input_contract_mismatches_prevent_request(self):
        for old, new in (('dimension=64', 'dimension=128'), ('ws-test.', 'ws-another.')):
            self.config.write_text(self.config_text.replace(old, new))
            self.assert_precheck_failure(self.run_query(), 'encoding_compatibility')
        self.config.write_text(self.config_text)
        for field, value in (('prefix', 'new-prefix'), ('query_text_type', 'document'),
                             ('document_input', 'cleaned'), ('normalization', 'unit')):
            public = embedding.EmbeddingConfig(ENDPOINT, KEY, 64).public()
            public[field] = value
            with patch.object(embedding.EmbeddingConfig, 'public', return_value=public):
                self.assert_precheck_failure(self.run_query(), 'encoding_compatibility')

    def test_explicit_endpoint_is_used_without_rewriting_config(self):
        self.config.write_text(self.config_text.replace(f'endpoint="{ENDPOINT}"\n', ''))
        before = self.config.read_bytes()
        result = self.run_query(endpoint=ENDPOINT)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.request.call_args.args[0].endpoint, ENDPOINT)
        self.assertEqual(self.config.read_bytes(), before)

    def test_http_error_retains_known_usage_and_drops_raw_error(self):
        data = {'usage': {'total_tokens': 7}, 'request_id': KEY, 'message': KEY, 'code': 'Forbidden'}
        self.request.return_value = reply(data, status=403)
        with patch.object(retrieval, 'search') as search:
            result = self.run_query()
            search.assert_not_called()
        self.request.assert_called_once()
        self.assertEqual(result['error']['category'], 'http_error')
        self.assertEqual(result['usage'], {'known_total_tokens': 7, 'complete': True})
        self.assertIsNone(result['requests'][0]['request_id'])
        self.assertIsNone(result['query'])

    def test_timeout_counts_one_attempt_and_unknown_usage_without_retry(self):
        self.request.side_effect = TimeoutError(KEY)
        result = self.run_query()
        self.request.assert_called_once()
        self.assertEqual(result['error']['category'], 'network_error')
        self.assertEqual(result['http_attempts'], 1)
        self.assertEqual(result['usage'], {'known_total_tokens': 0, 'complete': False})
        self.assertIsNone(result['retrieval'])

    def test_bad_responses_retain_usage_and_never_retrieve(self):
        for change in ('index', 'missing_index', 'count', 'dimension', 'bool', 'zero', 'nan', 'inf'):
            data = payload()
            row = data['output']['embeddings'][0]
            if change == 'index': row['text_index'] = 1
            elif change == 'missing_index': del row['text_index']
            elif change == 'count': data['output']['embeddings'].append(deepcopy(row))
            elif change == 'dimension': row['embedding'].pop()
            elif change == 'bool': row['embedding'][0] = True
            elif change == 'zero': row['embedding'] = [0] * 64
            elif change == 'nan': row['embedding'][0] = float('nan')
            else: row['embedding'][0] = float('inf')
            self.request.reset_mock()
            self.request.return_value = reply(data)
            with patch.object(retrieval, 'search') as search:
                result = self.run_query()
                search.assert_not_called()
            self.request.assert_called_once()
            self.assertEqual(result['error']['stage'], 'response_validation')
            self.assertEqual(result['usage']['known_total_tokens'], 17)
            self.assertTrue(result['usage']['complete'])
            self.assertIsNone(result['query'])

    def test_non_json_response_safe_unknown_usage(self):
        self.request.return_value = embedding.Reply(200, KEY.encode())
        result = self.run_query()
        self.request.assert_called_once()
        self.assertEqual(result['error']['stage'], 'response_validation')
        self.assertFalse(result['usage']['complete'])

    def test_valid_vector_with_missing_or_invalid_usage_can_retrieve(self):
        for usage in (None, {'total_tokens': True}, {'total_tokens': -1}):
            data = payload()
            data['usage'] = usage
            self.request.return_value = reply(data)
            self.request.reset_mock()
            result = self.run_query()
            self.assertEqual(result['status'], 'succeeded')
            self.assertFalse(result['usage']['complete'])
            self.assertIsNotNone(result['query'])
            self.request.assert_called_once()

    def test_source_changes_during_request_keep_vector_usage_but_no_candidates(self):
        def change_during_request(*args):
            path = self.knowledge / 'migration-guide.md'
            path.write_text(path.read_text() + '\n请求期间修改\n')
            return reply()
        self.request.side_effect = change_during_request
        result = self.run_query()
        self.request.assert_called_once()
        self.assertEqual(result['error']['stage'], 'retrieval')
        self.assertEqual(result['requests'][0]['status'], 'succeeded')
        self.assertIsNotNone(result['query'])
        self.assertIsNone(result['retrieval'])
        self.assertEqual(result['usage']['known_total_tokens'], 17)

    def cli_args(self, output):
        return ['--question', QUESTION, '--prepared', str(self.prepared), '--artifact', str(self.artifact),
                '--config', str(self.config), '--knowledge', str(self.knowledge), '--output', str(output)]

    def test_cli_success_and_failure_save_results_but_do_not_print_vectors(self):
        output = self.root / 'cli.json'
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
            self.assertEqual(live.main(self.cli_args(output)), 0)
        result = json.loads(output.read_text())
        self.assertIn('cosine=', stdout.getvalue())
        self.assertIn(retrieval.NOTICE, stdout.getvalue())
        self.assertNotIn(str(result['query']['vector']), stdout.getvalue())
        self.assertNotIn(KEY, stdout.getvalue())
        self.request.reset_mock()
        self.request.side_effect = RuntimeError(KEY)
        failed_output = self.root / 'cli-failed.json'
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(live.main(self.cli_args(failed_output)), 1)
        self.assertNotIn(KEY, stdout.getvalue() + stderr.getvalue() + failed_output.read_text())
        self.assertEqual(json.loads(failed_output.read_text())['status'], 'failed')
        self.request.assert_called_once()

    def test_write_flush_and_close_failures_return_nonzero_without_secret_or_rerun(self):
        original_open = Path.open
        for operation in ('write', 'flush', 'close'):
            output = self.root / f'fail-{operation}.json'
            class FailingHandle:
                def __init__(self, handle): self.handle = handle
                def __enter__(self): return self
                def __exit__(self, *args):
                    self.handle.close()
                    if operation == 'close': raise OSError(KEY)
                def write(self, text):
                    if operation == 'write': raise OSError(KEY)
                    return self.handle.write(text)
                def flush(self):
                    if operation == 'flush': raise OSError(KEY)
                    self.handle.flush()
            def failing_open(path, *args, **kwargs):
                handle = original_open(path, *args, **kwargs)
                return FailingHandle(handle) if path == output else handle
            self.request.reset_mock()
            with patch.object(Path, 'open', failing_open), redirect_stdout(io.StringIO()) as stdout, \
                    redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(live.main(self.cli_args(output)), 1)
            self.request.assert_called_once()
            self.assertNotIn(KEY, stdout.getvalue() + stderr.getvalue())
            self.assertIn('保存失败', stderr.getvalue())
            self.assertIn('HTTP尝试=1', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
