"""E2b contracts: generated temporary inputs only; API/config access forbidden."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import dashscope_embedding as emb
import prepare_corpus as corpus
import json_retrieval as retrieval


class JsonRetrievalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.knowledge = self.root / 'knowledge'
        shutil.copytree(corpus.DEFAULT_KNOWLEDGE, self.knowledge)
        self.prepared = self.root / 'prepared'
        self.manifest = corpus.prepare(self.knowledge, self.prepared)
        self.chunks = json.loads((self.prepared / 'corpus/chunks.json').read_text())
        self.record_path = self.root / 'e2a.json'
        self.output = self.root / 'vectors.json'
        self.record = {
            'artifact_type': 'e2a_embedding_validation', 'format_version': 1,
            'status': 'succeeded', 'error': None, 'e1_build_id': self.manifest['build_id'],
            'encoding': {**retrieval.CONTRACT_FIXED, 'dimension': 64,
                         'endpoint': 'https://ws-test.cn-beijing.maas.aliyuncs.com' + emb.API_PATH,
                         'timeout_seconds': 30, 'batch_size': 10},
            'selection': {'available_chunks': len(self.chunks), 'selected_chunks': len(self.chunks),
                          'limited_sample': False},
            'documents': [{**{k: c[k] for k in ('chunk_id', 'document_id', 'source_path', 'source')},
                           'input_row': i, 'vector': [i + 1.0] + [0.0] * 63, 'norm': -999}
                          for i, c in enumerate(self.chunks)],
            'query': {'text': '已编码的问题', 'vector': [2.0] + [0.0] * 63},
        }
        self.save_record()
        # Any accidental config read or request fails the entire test, not just a mock result assertion.
        for name in ('read_embedding_config', 'request_embeddings', 'build_opener'):
            mock = patch.object(emb, name, side_effect=AssertionError('E2b must remain offline')).start()
            self.addCleanup(patch.stopall)

    def save_record(self):
        self.record_path.write_bytes(corpus.json_bytes(self.record))

    def build(self):
        return retrieval.build(self.record_path, self.prepared, self.output, self.knowledge)

    def search(self, artifact, query=None, encoding=None, k=3):
        return retrieval.search(artifact, query or self.record['query'], encoding or self.record['encoding'], k,
                                prepared=self.prepared, knowledge=self.knowledge)

    def test_full_import_deterministic_source_join_and_untrusted_norm(self):
        first = self.build()
        second_path = self.root / 'other.json'
        retrieval.build(self.record_path, self.prepared, second_path, self.knowledge)
        self.assertEqual(self.output.read_bytes(), second_path.read_bytes())
        self.assertEqual(len(first['documents']), len(self.chunks))
        self.assertNotIn('timeout_seconds', first['encoding'])
        for row, chunk in zip(first['documents'], self.chunks):
            self.assertEqual({k: v for k, v in row.items() if k != 'vector'}, chunk)
            lines = corpus.source_lines((self.knowledge / row['source_path']).read_text())
            self.assertEqual(row['text'], ''.join(lines[row['source']['start_line']-1:row['source']['end_line']]))
        result = self.search(first)
        self.assertEqual(result['returned_count'], 3)
        self.assertEqual(result['evidence_status'], 'candidates_only')
        self.assertTrue(all(h['score'] == 1.0 for h in result['hits']))

    def test_failed_partial_and_mismatched_build_imports_rejected(self):
        original = deepcopy(self.record)
        for mutation in ('failed', 'limited', 'count', 'build', 'version', 'empty'):
            self.record = deepcopy(original)
            if mutation == 'failed': self.record['status'] = 'failed'
            elif mutation == 'limited': self.record['selection']['limited_sample'] = True
            elif mutation == 'count': self.record['selection']['selected_chunks'] -= 1
            elif mutation == 'build': self.record['e1_build_id'] = 'other'
            elif mutation == 'version': self.record['format_version'] = True
            else: self.record['documents'] = []
            self.save_record()
            with self.subTest(mutation=mutation), self.assertRaises(retrieval.RetrievalError): self.build()
            self.assertFalse(self.output.exists())

    def test_missing_duplicate_extra_ids_and_source_mapping_rejected(self):
        original = deepcopy(self.record)
        for mutation in ('missing', 'duplicate', 'extra', 'source', 'document', 'row'):
            self.record = deepcopy(original)
            rows = self.record['documents']
            if mutation == 'missing': rows.pop()
            elif mutation == 'duplicate': rows[0] = deepcopy(rows[1])
            elif mutation == 'extra': rows[0]['chunk_id'] = 'unknown'
            elif mutation == 'source': rows[0]['source']['start_line'] += 1
            elif mutation == 'document': rows[0]['document_id'] = 'other'
            else: rows[0]['input_row'] = True
            self.save_record()
            with self.subTest(mutation=mutation), self.assertRaises(retrieval.RetrievalError): self.build()

    def test_document_order_joined_by_id_not_record_position(self):
        self.record['documents'].reverse()
        self.save_record()
        artifact = self.build()
        self.assertEqual([d['chunk_id'] for d in artifact['documents']], [c['chunk_id'] for c in self.chunks])
        self.assertEqual(artifact['documents'][0]['vector'][0], 1)

    def test_invalid_document_vectors_and_encoding_fail_import(self):
        original = deepcopy(self.record)
        for vector in ([1], [0]*64, [True]*64, ['1']*64, [float('inf')]*64, [float('nan')]*64):
            record = deepcopy(original)
            record['documents'][0]['vector'] = vector
            with self.subTest(vector=repr(vector[:1])), self.assertRaises(emb.EmbeddingError):
                retrieval.validate_coverage(record, self.manifest, self.chunks)
        for field, value in [('dimension', True), ('model', 'other'), ('prefix', 'new'), ('document_input', 'cleaned')]:
            self.record = deepcopy(original)
            self.record['encoding'][field] = value
            self.save_record()
            with self.assertRaises(retrieval.RetrievalError): self.build()

    def test_unknown_usage_is_not_vector_failure(self):
        self.record['usage'] = {'known_total_tokens': 0, 'complete': False}
        self.save_record()
        self.assertEqual(len(self.build()['documents']), len(self.chunks))

    def test_checksum_covers_vectors_text_encoding_and_provenance(self):
        artifact = self.build()
        for mutation in ('vector', 'text', 'encoding', 'provenance'):
            changed = deepcopy(artifact)
            if mutation == 'vector': changed['documents'][0]['vector'][0] += 1
            elif mutation == 'text': changed['documents'][0]['text'] += 'changed'
            elif mutation == 'encoding': changed['encoding']['dimension'] = 128
            else: changed['provenance']['e2a_record_sha256'] = 'other'
            with self.assertRaisesRegex(retrieval.RetrievalError, '完整性'): self.search(changed)

    def test_resealed_wrong_source_or_incomplete_corpus_still_rejected(self):
        artifact = self.build()
        for mutation in ('text', 'missing', 'duplicate', 'build'):
            body = deepcopy(artifact)
            body.pop('content_sha256')
            if mutation == 'text': body['documents'][0]['text'] = 'wrong'
            elif mutation == 'missing': body['documents'].pop()
            elif mutation == 'duplicate': body['documents'][0] = deepcopy(body['documents'][1])
            else: body['e1_build_id'] = 'wrong'
            with self.assertRaises(retrieval.RetrievalError): self.search(retrieval.seal(body))

    def test_stale_source_and_processing_block_search(self):
        artifact = self.build()
        with self.assertRaises(corpus.RebuildRequired):
            retrieval.search(artifact, self.record['query'], self.record['encoding'], 3,
                             prepared=self.prepared, knowledge=self.knowledge, max_chars=1300)
        path = self.knowledge / 'migration-guide.md'
        path.write_text(path.read_text() + '\n新条款\n')
        with self.assertRaises(corpus.RebuildRequired): self.search(artifact)

    def test_missing_and_corrupt_artifact_and_e1_rejected(self):
        artifact = self.build()
        for data in (b'', b'{', b'{}', b'{"x":1,"x":2}', b'{"x":NaN}'):
            self.output.write_bytes(data)
            with self.assertRaises((retrieval.RetrievalError, corpus.CorpusError)):
                retrieval.load_checked(self.output, self.prepared, self.knowledge)
        self.output.unlink()
        with self.assertRaises(corpus.CorpusError): retrieval.load_checked(self.output, self.prepared, self.knowledge)
        (self.prepared / 'corpus/chunks.json').write_text('[]')
        with self.assertRaises(corpus.CorpusError): self.search(artifact)

    def test_query_compatibility_excludes_runtime_but_includes_endpoint(self):
        artifact = self.build()
        encoding = deepcopy(self.record['encoding'])
        encoding.update(timeout_seconds=999, batch_size=1, usage={'total_tokens': 20})
        self.assertEqual(self.search(artifact, encoding=encoding)['returned_count'], 3)
        for key, value in [('model', 'other'), ('dimension', 128), ('prefix', 'new'),
                           ('normalization', 'unit'), ('query_text_type', 'document'),
                           ('endpoint', 'https://ws-another.cn-beijing.maas.aliyuncs.com' + emb.API_PATH)]:
            changed = {**encoding, key: value}
            with self.subTest(key=key), self.assertRaises(retrieval.RetrievalError): self.search(artifact, encoding=changed)

    def test_query_text_from_record_no_override_and_query_vector_rechecked(self):
        query, contract = retrieval.import_query(self.record_path)
        result = self.search(self.build(), query, contract)
        self.assertEqual(result['question'], self.record['query']['text'])
        for vector in ([0]*64, [1], [True]*64, [float('nan')]*64):
            with self.assertRaises(emb.EmbeddingError): self.search(retrieval.read_json(self.output), {'text': 'q', 'vector': vector})

    def test_cosine_hand_calculable_nonunit_negative_and_stable_ties(self):
        docs = [{'chunk_id': cid, 'vector': vector} for cid, vector in
                [('z', [3, 4]), ('b', [0, 2]), ('a', [0, 5]), ('n', [-2, 0]), ('p', [9, 0])]]
        result = retrieval.rank_vectors(docs, [2, 0], 2, 10)
        self.assertEqual([h['chunk_id'] for h in result], ['p', 'z', 'a', 'b', 'n'])
        for row, expected in zip(result, [1, .6, 0, 0, -1]): self.assertAlmostEqual(row['score'], expected)
        self.assertEqual(retrieval.rank_vectors(list(reversed(docs)), [2, 0], 2, 10), result)

    def test_top_k_strict_positive_and_actual_count(self):
        artifact = self.build()
        for k in (0, -1, True, 1.5, '3'):
            with self.assertRaises(retrieval.RetrievalError): self.search(artifact, k=k)
        result = self.search(artifact, k=100)
        self.assertEqual(result['returned_count'], len(self.chunks))
        self.assertEqual(result['requested_top_k'], 100)

    def test_existing_output_preserved_and_partial_write_not_loadable(self):
        self.output.write_text('keep')
        with self.assertRaises(retrieval.RetrievalError): self.build()
        with self.assertRaises(retrieval.RetrievalError): retrieval.write_new(self.output, {'a': 1})
        self.assertEqual(self.output.read_text(), 'keep')
        partial = self.root / 'partial.json'
        original = Path.open
        class FailedWriter:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def write(self, data):
                with original(partial, 'wb') as handle: handle.write(data[:40])
                raise OSError('disk failed')
        self.output.unlink()
        artifact = self.build()
        with patch.object(Path, 'open', return_value=FailedWriter()):
            with self.assertRaises(retrieval.RetrievalError): retrieval.write_new(partial, artifact)
        with self.assertRaises(corpus.CorpusError): retrieval.load_checked(partial, self.prepared, self.knowledge)

    def test_cli_build_check_search_and_refuse_result_overwrite(self):
        common = ['--prepared', str(self.prepared), '--knowledge', str(self.knowledge)]
        result_path = self.root / 'result.json'
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
            self.assertEqual(retrieval.main(['build', *common, '--record', str(self.record_path), '--output', str(self.output)]), 0)
            self.assertEqual(retrieval.main(['check', *common, '--artifact', str(self.output)]), 0)
            args = ['search', *common, '--artifact', str(self.output), '--query-record', str(self.record_path),
                    '--top-k', '3', '--output', str(result_path)]
            self.assertEqual(retrieval.main(args), 0)
            previous = result_path.read_bytes()
            self.assertEqual(retrieval.main(args), 1)
            self.assertEqual(result_path.read_bytes(), previous)
        self.assertIn('已编码的问题', stdout.getvalue())
        self.assertEqual(json.loads(previous)['returned_count'], 3)


if __name__ == '__main__':
    unittest.main()
