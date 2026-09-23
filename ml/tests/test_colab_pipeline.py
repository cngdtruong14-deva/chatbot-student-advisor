import ast
import json
import tempfile
import unittest
from pathlib import Path
from advisor_core.rag import chunk_markdown,lexical_search,evidence_response,applicable
from ml.scripts.common import save,sha,require_approval,load,read_jsonl
from ml.scripts.rag_eval import prepare_corpus, validate_benchmark_questions, write_final_approval_template
from ml.scripts.build_rag_benchmark import _chunks


class ColabTests(unittest.TestCase):
    def test_notebooks_clean_and_compilable(self):
        root=Path(__file__).resolve().parents[1]/'notebooks'
        notebooks=list(root.glob('*.ipynb'))
        self.assertEqual(len(notebooks),7)
        for file in notebooks:
            data=json.loads(file.read_text(encoding='utf-8'))
            self.assertEqual(data['nbformat'],4)
            for cell in data['cells']:
                if cell['cell_type']=='code':
                    self.assertEqual(cell['outputs'],[])
                    self.assertIsNone(cell['execution_count'])
                    ast.parse(''.join(cell['source']))

    def chunks(self):
        return chunk_markdown('DEMO học lại lấy điểm cao nhất.\n\nTối đa 18 tín chỉ một kỳ.',
          document_id='demo',version_id='1',scope='demo_academic',source='fixture',valid_from='2026-09-06')

    def test_scope_and_historical_filter_before_retrieval(self):
        chunks=self.chunks()
        self.assertEqual(lexical_search(chunks,'học lại','institution_private','2026-09-06'),[])
        self.assertEqual(lexical_search(chunks,'học lại','demo_academic','2025-09-06'),[])
        self.assertIn('cao nhất',lexical_search(chunks,'học lại','demo_academic','2026-09-06')[0]['chunk']['text'])

    def test_stable_ids_and_no_llm_claim(self):
        self.assertEqual(self.chunks(),self.chunks())
        result=evidence_response(lexical_search(self.chunks(),'học lại','demo_academic','2026-09-06'),'học lại')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['generation_status'],'provider_unavailable')
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertTrue(result['citations'])

    def test_approval_bound_to_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);save(root/'report.json',{'actual':'fixture'})
            save(root/'approval.json',{'approved':True,'owner':'test-only','audit_sha256':sha(root/'report.json')})
            require_approval(root/'approval.json',sha(root/'report.json'))
            save(root/'report.json',{'actual':'changed'})
            with self.assertRaises(ValueError):
                require_approval(root/'approval.json',sha(root/'report.json'))

    def test_rag_index_is_explicitly_not_a_benchmark(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'demo.md'; source.write_text('Quy định DEMO.',encoding='utf-8')
            prepare_corpus(source,root/'rag',{'corpus_version':'fixture','scope':'demo_academic',
              'valid_from':'2026-09-06','max_chars':1600,'chunker_version':'paragraph-v1'})
            self.assertEqual(load(root/'rag/evaluation_status.json')['status'],'NOT_EVALUATED')

    def test_full_rag_benchmark_draft_and_final_approval_template(self):
        root=Path(__file__).resolve().parents[1]
        questions=read_jsonl(root/'rag/questions_benchmark_draft.jsonl')
        validate_benchmark_questions(questions,list(_chunks().values()),require_reviewed=False)
        self.assertEqual(len(questions),120)
        with self.assertRaisesRegex(ValueError,'HUMAN_GOLD_REVIEW_REQUIRED'):
            validate_benchmark_questions(questions,list(_chunks().values()),require_reviewed=True)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'approval.template.json'
            write_final_approval_template(root/'rag/questions_benchmark_draft.jsonl',
                {'corpus_version':'fixture'},path)
            approval=load(path)
            self.assertFalse(approval['approved'])
            self.assertEqual(approval['questions_sha256'],sha(root/'rag/questions_benchmark_draft.jsonl'))


if __name__=='__main__':
    unittest.main()
