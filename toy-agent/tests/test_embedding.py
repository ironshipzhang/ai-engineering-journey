"""Offline tests: fake credentials, temporary corpus and mocked HTTP only."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

import dashscope_embedding as emb
import prepare_corpus as corpus
import verify_embedding as verify

ENDPOINT = 'https://ws-test.cn-beijing.maas.aliyuncs.com' + emb.API_PATH
KEY = 'fake-test-credential'


def payload(count, dimension=64):
    return {'request_id': 'test-request', 'usage': {'total_tokens': 12},
            'output': {'embeddings': [{'index': i, 'embedding': [i + 1.0] * dimension}
                                      for i in reversed(range(count))]}}


def reply(count):
    return emb.Reply(200, json.dumps(payload(count)).encode())


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / 'config.toml'
        self.config.write_text('[embedding]\nprovider="dashscope"\nmodel="text-embedding-v4"\n'
                               f'api_key="{KEY}"\nendpoint="{ENDPOINT}"\ndimension=64\n')
        self.knowledge = self.root / 'knowledge'
        shutil.copytree(corpus.DEFAULT_KNOWLEDGE, self.knowledge)
        self.prepared = self.root / 'prepared'
        corpus.prepare(self.knowledge, self.prepared)

    def run_fake(self, side_effect):
        with patch.object(emb, 'request_embeddings', side_effect=side_effect) as request:
            result = verify.run_validation(self.config, self.prepared, self.knowledge)
        return result, request

    def test_config_valid_override_and_no_secret_in_public_repr(self):
        config = emb.read_embedding_config(self.config, ENDPOINT)
        self.assertEqual(config.dimension, 64)
        self.assertNotIn(KEY, repr(config))
        self.assertNotIn(KEY, json.dumps(config.public()))

    def test_invalid_configs_prevent_requests(self):
        original = self.config.read_text()
        for old, new in [('dashscope', 'other'), ('text-embedding-v4', 'other'),
                         (KEY, 'YOUR_EMBEDDING_API_KEY'), ('dimension=64', 'dimension=true'),
                         (ENDPOINT, 'https://example.com')]:
            with self.subTest(new=new):
                self.config.write_text(original.replace(old, new))
                result, request = self.run_fake(AssertionError('must not call'))
                request.assert_not_called()
                self.assertEqual(result['error']['category'], 'configuration')
        self.config.write_text('[invalid')
        result, request = self.run_fake(AssertionError('must not call'))
        request.assert_not_called()
        self.assertEqual(result['http_attempts'], 0)

    def test_batches_mapping_and_query_type(self):
        result, request = self.run_fake(lambda config, texts, kind: reply(len(texts)))
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual([(len(c.args[1]), c.args[2]) for c in request.call_args_list],
                         [(10, 'document'), (5, 'document'), (1, 'query')])
        self.assertEqual([r['input_row'] for r in result['documents']], list(range(15)))
        self.assertEqual(result['documents'][0]['vector'][0], 1)
        self.assertEqual(result['documents'][9]['response_index'], 9)
        self.assertEqual(result['usage'], {'known_total_tokens': 36, 'complete': True})
        self.assertNotIn(KEY, json.dumps(result))

    def test_stale_and_corrupt_corpus_block_before_credentials(self):
        chunks = self.prepared / 'corpus/chunks.json'
        original = chunks.read_bytes()
        chunks.write_bytes(b'broken')
        with patch.object(emb, 'read_embedding_config') as config:
            result, request = self.run_fake(AssertionError('must not call'))
            config.assert_not_called()
            request.assert_not_called()
            self.assertEqual(result['error']['category'], 'corpus_check')
        chunks.write_bytes(original)
        path = next(self.knowledge.glob('*.md'))
        path.write_text(path.read_text() + '\nchanged\n')
        result, request = self.run_fake(AssertionError('must not call'))
        request.assert_not_called()
        self.assertEqual(result['http_attempts'], 0)

    def test_bad_second_response_retains_first_batch_and_known_usage(self):
        bad = payload(5)
        bad['output']['embeddings'][0]['embedding'] = [0] * 64
        result, request = self.run_fake([reply(10), emb.Reply(200, json.dumps(bad).encode())])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(result['documents']), 10)
        self.assertIsNone(result['query'])
        self.assertEqual(result['usage']['known_total_tokens'], 24)
        self.assertEqual(result['error']['category'], 'response_validation')

    def test_http_and_network_failures_stop_and_unknown_is_not_zero_billing(self):
        for failure in [emb.Reply(401, (KEY + ' raw secret error').encode()),
                        emb.EmbeddingError('network_error', 'safe network failure')]:
            result, request = self.run_fake([failure])
            self.assertEqual(request.call_count, 1)
            self.assertEqual(result['http_attempts'], 1)
            self.assertFalse(result['usage']['complete'])
            self.assertNotIn(KEY, json.dumps(result))

    def test_missing_usage_can_succeed_but_is_unknown(self):
        def response(config, texts, kind):
            data = payload(len(texts))
            del data['usage']
            return emb.Reply(200, json.dumps(data).encode())
        result, _ = self.run_fake(response)
        self.assertEqual(result['status'], 'succeeded')
        self.assertFalse(result['usage']['complete'])

    def test_response_index_contract(self):
        for change in ['missing', 'duplicate', 'out_of_range', 'bool', 'ambiguous', 'count']:
            data = payload(2)
            rows = data['output']['embeddings']
            if change == 'missing': del rows[0]['index']
            elif change == 'duplicate': rows[0]['index'] = rows[1]['index']
            elif change == 'out_of_range': rows[0]['index'] = 2
            elif change == 'bool': rows[0]['index'] = True
            elif change == 'ambiguous': rows[0]['text_index'] = 1
            else: rows.pop()
            with self.subTest(change=change), self.assertRaises(emb.EmbeddingError):
                emb.validate_vectors(data, 2, 64)

    def test_vector_contract(self):
        for vector in [[1], [0] * 64, [True] * 64, ['1'] * 64,
                       [float('nan')] * 64, [float('inf')] * 64, [10**1000] * 64]:
            data = payload(1)
            data['output']['embeddings'][0]['embedding'] = vector
            with self.assertRaises(emb.EmbeddingError):
                emb.validate_vectors(data, 1, 64)

    def test_native_text_index_alias_and_norm_without_normalization(self):
        data = payload(1)
        data['output']['embeddings'][0]['text_index'] = data['output']['embeddings'][0].pop('index')
        row = emb.validate_vectors(data, 1, 64)[0]
        self.assertEqual(row['norm'], 8)
        self.assertEqual(row['vector'], [1] * 64)

    def test_output_reservation_refuses_overwrite_before_work(self):
        output = self.root / 'result.json'
        output.write_text('keep')
        with patch.object(verify, 'run_validation') as run, redirect_stderr(io.StringIO()):
            self.assertEqual(verify.main(['--prepared', str(self.prepared), '--output', str(output)]), 1)
        run.assert_not_called()
        self.assertEqual(output.read_text(), 'keep')

    def test_output_saves_failure_safely(self):
        output = self.root / 'result.json'
        with patch.object(emb, 'request_embeddings', side_effect=TimeoutError(KEY)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = verify.main(['--config', str(self.config), '--prepared', str(self.prepared),
                                '--knowledge', str(self.knowledge), '--output', str(output)])
        self.assertEqual(code, 1)
        self.assertNotIn(KEY, output.read_text())
        self.assertEqual(json.loads(output.read_text())['http_attempts'], 1)

    def test_text_guard_no_truncation_or_request(self):
        for texts in [[], ['x'] * 11, [''], ['中' * 3000]]:
            with patch.object(emb, 'build_opener') as opener, self.assertRaises(emb.EmbeddingError):
                emb.request_embeddings(emb.read_embedding_config(self.config), texts, 'document')
            opener.assert_not_called()

    def test_transport_timeout_payload_no_redirect_or_retry(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.code = 200
        response.read.return_value = b'{}'
        response.headers = {}
        with patch.object(emb, 'build_opener') as builder:
            builder.return_value.open.return_value = response
            emb.request_embeddings(emb.read_embedding_config(self.config), ['原文'], 'query')
            args = builder.return_value.open.call_args
            self.assertEqual(args.kwargs['timeout'], 30)
            self.assertEqual(json.loads(args.args[0].data)['parameters']['text_type'], 'query')
            self.assertEqual(json.loads(args.args[0].data)['input']['texts'], ['原文'])
            self.assertIsInstance(builder.call_args.args[0], emb.NoRedirect)
            builder.return_value.open.assert_called_once()
        with patch.object(emb, 'build_opener') as builder:
            builder.return_value.open.side_effect = TimeoutError(KEY)
            with self.assertRaises(emb.EmbeddingError) as error:
                emb.request_embeddings(emb.read_embedding_config(self.config), ['x'], 'document')
            self.assertNotIn(KEY, str(error.exception))
            builder.return_value.open.assert_called_once()

    def test_http_error_body_is_captured_without_retry(self):
        error = HTTPError(ENDPOINT, 403, 'forbidden', {}, io.BytesIO(b'{}'))
        with patch.object(emb, 'build_opener') as builder:
            builder.return_value.open.side_effect = error
            response = emb.request_embeddings(emb.read_embedding_config(self.config), ['x'], 'document')
            self.assertEqual(response.status, 403)
            builder.return_value.open.assert_called_once()


if __name__ == '__main__':
    unittest.main()
