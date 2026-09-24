"""Real PostgreSQL checks, all fixture changes rolled back in one outer transaction."""
import os
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from app import api as routes, knowledge
from app.main import app
from app.store import engine, one, run


@unittest.skipUnless(os.environ.get('ADVISOR_DOCUMENT_DB_TEST')=='1', 'explicit database test required')
class DocumentDBTests(unittest.TestCase):
    def setUp(self):
        self.mode=patch.dict(os.environ,{'RAG_METHOD':'keyword','RAG_LLM_ENABLED':'0'});self.mode.start()
        self.conn=engine().connect(); self.outer=self.conn.begin()
        uid=uuid4()
        run(self.conn,"INSERT INTO app.users(id,email,password_hash,role) VALUES(:id,:email,'test-only','admin')",id=uid,email=f'{uid}@test.invalid')
        self.admin={'id':uid,'role':'admin'}
        self.user=self.admin
        @contextmanager
        def isolated():
            with self.conn.begin_nested(): yield self.conn
        self.patches=[patch('app.knowledge.transaction',isolated),patch('app.api.transaction',isolated)]
        for p in self.patches:p.start()
        app.dependency_overrides[routes.actor]=lambda:self.user
        self.client=TestClient(app)

    def tearDown(self):
        self.mode.stop()
        app.dependency_overrides.clear()
        for p in self.patches:p.stop()
        self.outer.rollback();self.conn.close()

    def document(self,**kwargs):
        base = dict(title='Fixture thủ tục',source='synthetic fixture',version='1',content='Zebrafixture: cần hai biểu mẫu để đăng ký thử nghiệm.',valid_from='2026-01-01')
        return base | kwargs

    def test_register_ingest_activate_search_citation_chat(self):
        payload=self.document()
        r=self.client.post('/api/v1/admin/documents',json=payload);self.assertEqual(r.status_code,200,r.text)
        v=r.json()['data']['id'];self.assertEqual(r.json()['data']['status'],'pending')
        self.assertEqual(self.client.post('/api/v1/admin/documents',json=payload).json()['data']['id'],v)
        self.assertFalse(knowledge.search('Zebrafixture')['citations'])
        with self.assertRaisesRegex(ValueError,'NOT_READY'):knowledge.activate(v)
        knowledge.ingest(v);knowledge.activate(v)
        result=self.client.post('/api/v1/knowledge/search',json={'query':'Zebrafixture'}).json()['data']
        self.assertTrue(result['citations']); self.assertIsNone(result['answer'])
        cid=result['citations'][0]['chunk_id']
        self.assertEqual(self.client.get('/api/v1/knowledge/chunks/'+cid).status_code,200)
        sid=self.client.post('/api/v1/chat/sessions',json={}).json()['data']['id']
        turn={'message':'Zebrafixture','client_turn_id':str(uuid4())}
        result=self.client.post(f'/api/v1/chat/sessions/{sid}/messages',json=turn).json()['data']
        self.assertTrue(result['citations']);self.assertEqual(result['cards'][0]['type'],'evidence')
        self.assertEqual(self.client.post(f'/api/v1/chat/sessions/{sid}/messages',json=turn).json()['data'],result)
        class GroundedProvider:
            def generate(self,query,matches):
                return {'status':'completed','answer':'Cần hai biểu mẫu theo tài liệu DEMO.',
                        'claims':[{'text':'Cần hai biểu mẫu','citation_ids':[matches[0]['chunk']['chunk_id']]}]}
        with patch('app.llm_runtime.OpenAICompatibleProvider',return_value=GroundedProvider()):
            evidence=knowledge.search('Zebrafixture')
            self.assertEqual(evidence['status'],'answered')
            generated=self.client.post(f'/api/v1/chat/sessions/{sid}/messages',json={'message':'Zebrafixture','client_turn_id':str(uuid4())}).json()['data']
            self.assertEqual(generated['status'],'completed')
            self.assertEqual(generated['provider_status'],'completed')
            self.assertEqual(generated['answer'],'Cần hai biểu mẫu theo tài liệu DEMO.')

    def test_permission_version_and_date_filters(self):
        self.user={'id':uuid4(),'role':'student'}
        self.assertEqual(self.client.post('/api/v1/admin/documents',json=self.document()).status_code,403)
        self.assertEqual(self.client.get('/api/v1/admin/documents').status_code,403)
        self.user=self.admin
        doc=self.client.post('/api/v1/admin/documents',json=self.document()).json()['data']
        knowledge.ingest(doc['id']);knowledge.activate(doc['id'])
        self.assertFalse(knowledge.search('Zebrafixture',datetime(2020,1,1))['citations'])
        self.assertFalse(knowledge.search('Zebrafixture',document_types=['procedure'])['citations'])
        payload=self.document();payload.update(document_id=doc['document_id'],content='Changed content')
        self.assertEqual(self.client.post('/api/v1/admin/documents',json=payload).status_code,409)
        payload['version']='2'
        second=self.client.post('/api/v1/admin/documents',json=payload).json()['data']
        knowledge.ingest(second['id'])
        with self.assertRaisesRegex(ValueError,'INTERVAL_CONFLICT'): knowledge.activate(second['id'])
        self.assertTrue(knowledge.search('Zebrafixture')['citations'])

    def test_utt_test_corpus_is_labeled_isolated_and_admin_only(self):
        payload = self.document(title='UTT test only', source='drive:test-file-id',
                                content='UTTTEST quy định thử nghiệm.', corpus_scope='utt_test')
        registered = self.client.post('/api/v1/admin/documents', json=payload)
        self.assertEqual(registered.status_code, 200, registered.text)
        item = registered.json()['data']
        self.assertEqual(item['scope_key'], 'utt_test')
        self.assertEqual(item['data_origin'], 'user_provided_institutional_document')
        self.assertEqual(item['review_state'], 'test_only')
        self.assertEqual(self.client.post('/api/v1/admin/documents/'+item['id']+'/ingest').status_code, 200)
        self.assertEqual(self.client.post('/api/v1/admin/documents/'+item['id']+'/activate').status_code, 200)
        demo = knowledge.search('UTTTEST')
        self.assertFalse(demo['citations'])
        utt = self.client.post('/api/v1/knowledge/search', json={'query':'UTTTEST','corpus_scope':'utt_test'})
        self.assertEqual(utt.status_code, 200, utt.text)
        self.assertTrue(utt.json()['data']['citations'])
        self.assertTrue(utt.json()['data']['test_only'])
        self.assertIn('chưa được xác minh', utt.json()['data']['warning'])
        created = self.client.post('/api/v1/chat/sessions', json={'corpus_scope':'utt_test'})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()['data']['corpus_scope'], 'utt_test')
        self.user={'id':uuid4(),'role':'student'}
        self.assertEqual(self.client.post('/api/v1/knowledge/search', json={'query':'UTTTEST','corpus_scope':'utt_test'}).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/chat/sessions', json={'corpus_scope':'utt_test'}).status_code, 403)
        demo = one(self.conn, "SELECT user_id FROM app.students WHERE data_origin='synthetic' LIMIT 1")
        self.assertIsNotNone(demo, 'Seeded demo student required for this integration test')
        self.user={'id':demo['user_id'],'role':'student'}
        self.assertEqual(self.client.post('/api/v1/knowledge/search',json={'query':'UTTTEST','corpus_scope':'utt_test'}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/chat/sessions',json={'corpus_scope':'utt_test'}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/chat/sessions',json={'corpus_scope':'utt_corpus'}).status_code,200)
        self.assertEqual(self.client.post('/api/v1/admin/documents',json=payload).status_code,403)

    def test_export_contains_only_active_approved_chunks_and_hashes(self):
        doc=self.client.post('/api/v1/admin/documents',json=self.document()).json()['data']
        knowledge.ingest(doc['id']); knowledge.activate(doc['id'])
        exported=knowledge.export_corpus()
        self.assertEqual(exported['export_format'],'approved-corpus-v1')
        self.assertTrue(exported['chunks'])
        self.assertTrue(exported['chunks_sha256'] and exported['config_sha256'])

    def test_admin_can_extract_pdf_but_student_cannot(self):
        from tests.test_document_extract import simple_pdf
        files={'file':('policy.pdf',simple_pdf(),'application/pdf')}
        response=self.client.post('/api/v1/admin/documents/extract',files=files)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('Hoc lai DEMO-1',response.json()['data']['content'])
        self.user={'id':uuid4(),'role':'student'}
        self.assertEqual(self.client.post('/api/v1/admin/documents/extract',files=files).status_code,403)

    def test_replay_cannot_change_corpus_scope(self):
        payload=self.document(title='Scope replay isolation fixture')
        created=self.client.post('/api/v1/admin/documents',json=payload)
        self.assertEqual(created.status_code,200,created.text)
        changed=self.client.post('/api/v1/admin/documents',json=payload | {'corpus_scope':'utt_test'})
        self.assertEqual(changed.status_code,409,changed.text)

    def test_v2_document_has_v2_label(self):
        payload=self.document(title='Academic v2 label fixture',version='ACADEMIC-DEMO-2.0.0-rag-r1')
        created=self.client.post('/api/v1/admin/documents',json=payload)
        self.assertEqual(created.status_code,200,created.text)
        self.assertEqual(created.json()['data']['corpus_label'],'ACADEMIC-DEMO-2.0.0')

    def test_snapshot_is_immutable(self):
        case=one(self.conn,"INSERT INTO app.research_cases(owner_user_id,source_case_key,domain_id,data_origin) VALUES(:uid,'fixture','oulad','public_dataset') RETURNING id",uid=self.admin['id'])
        record={'case_id':str(case['id']),'domain_id':'oulad','data_origin':'public_dataset','feature_schema_id':'oulad_risk_day28','feature_schema_version':'1.0.0','cutoff_day':28,
          'source_completeness':{'static_verified':True,'vle_complete':True,'assessment_complete':True},
          'features':{'num_of_prev_attempts':0,'studied_credits':60,'vle_clicks_0_28':0,'vle_active_days_0_28':0,'assessment_submitted_count_0_28':0,'days_since_last_vle_activity':None}}
        response=self.client.post(f"/api/v1/research-cases/{case['id']}/feature-snapshots",json=record)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.post(f"/api/v1/research-cases/{case['id']}/feature-snapshots",json=record).status_code,200)
        with self.assertRaises(Exception):
            with self.conn.begin_nested():run(self.conn,'UPDATE app.feature_snapshots SET cutoff_day=28 WHERE id=:id',id=response.json()['data']['id'])

    def test_real_model_parity_history_and_owner(self):
        import json
        from app import ai_runtime
        approved=ai_runtime.approved_bundle()
        if not approved:self.skipTest('approved model absent')
        record=json.loads((approved['bundle']/'smoke_inputs.jsonl').read_text().splitlines()[0])
        expected=json.loads((approved['bundle']/'smoke_expected.jsonl').read_text().splitlines()[0])
        case=one(self.conn,"INSERT INTO app.research_cases(owner_user_id,source_case_key,domain_id,data_origin) VALUES(:uid,'parity',:domain,:origin) RETURNING id",uid=self.admin['id'],domain=record['domain_id'],origin=record['data_origin'])
        record['case_id']=str(case['id'])
        response=self.client.post(f"/api/v1/research-cases/{case['id']}/feature-snapshots",json=record)
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.post(f"/api/v1/research-cases/{case['id']}/predictions",json={})
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()['data'];self.assertAlmostEqual(result['probability'],expected['risk_probability'],places=6)
        history='/api/v1/predictions/'+result['id']
        self.assertEqual(self.client.get(history).status_code,200)
        explanation=self.client.get(history+'/explanation')
        self.assertEqual(explanation.status_code,200)
        self.assertEqual(len(explanation.json()['data']['contributions']),len(record['features']))
        self.user={'id':uuid4(),'role':'student'}
        for path in (history,history+'/explanation'):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.post(f"/api/v1/research-cases/{case['id']}/predictions",json={}).status_code,404)
