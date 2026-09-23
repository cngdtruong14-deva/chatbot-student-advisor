import hashlib
import json
import time
from pathlib import Path
import numpy as np
from advisor_core.rag import chunk_markdown,lexical_search,DenseRetriever,evidence_response
from .common import load,save,sha,jsonl,read_jsonl,require_approval


def validate_benchmark_questions(questions, chunks, require_reviewed):
    """Enforce the published 60-dev/60-test retrieval benchmark protocol."""
    chunk_ids={c['chunk_id'] for c in chunks}
    required={'question_id','split','benchmark_category','question','expected_scope','as_of',
              'expected_behavior','reference_claims','gold_evidence','gold_chunk_ids','reviewed'}
    if len(questions)!=120 or {q.get('split') for q in questions}!={'dev','test'}:
        raise ValueError('RAG_BENCHMARK_REQUIRES_120_QUESTIONS_60_DEV_60_TEST')
    if len({q.get('question_id') for q in questions})!=120:
        raise ValueError('RAG_QUESTION_IDS_MUST_BE_UNIQUE')
    for split in ('dev','test'):
        subset=[q for q in questions if q['split']==split]
        counts={kind:sum(q.get('benchmark_category')==kind for q in subset)
                for kind in ('answerable','insufficient_evidence','scope_or_version')}
        if len(subset)!=60 or counts!={'answerable':40,'insufficient_evidence':10,'scope_or_version':10}:
            raise ValueError('RAG_BENCHMARK_COMPOSITION_INVALID')
    for q in questions:
        if not required <= set(q):
            raise ValueError('RAG_BENCHMARK_REQUIRED_FIELDS_MISSING')
        if q['benchmark_category']=='answerable':
            if not q['reference_claims'] or not q['gold_evidence'] or not q['gold_chunk_ids'] or not set(q['gold_chunk_ids']) <= chunk_ids:
                raise ValueError('GOLD_EVIDENCE_MUST_BIND_TO_THIS_CORPUS')
        elif q['gold_chunk_ids'] or q['gold_evidence']:
            raise ValueError('NONANSWERABLE_QUESTIONS_MUST_NOT_HAVE_GOLD_EVIDENCE')
        if require_reviewed and q.get('reviewed') is not True:
            raise ValueError('HUMAN_GOLD_REVIEW_REQUIRED')


def write_final_approval_template(questions_path, config, destination):
    """Write, but never auto-approve, the immutable final-RAG test gate."""
    config_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    save(destination, {'approved':False, 'owner':'', 'config_sha256':config_hash,
                       'questions_sha256':sha(questions_path)})


def prepare_corpus(source,output,config):
    source,output=Path(source),Path(output)
    chunks=chunk_markdown(source.read_text(encoding='utf-8'),document_id='DEMO-1',version_id=config['corpus_version'],
      scope=config['scope'],source='repo:ml/rag/corpus/DEMO1.md',valid_from=config['valid_from'],max_chars=config['max_chars'])
    output.mkdir(parents=True,exist_ok=True)
    jsonl(output/'chunks.jsonl',chunks)
    save(output/'corpus_manifest.json',{'corpus_version':config['corpus_version'],'source_sha256':sha(source),
      'chunks_sha256':sha(output/'chunks.jsonl'),'source':'approved DP01-DP17; derived DEMO text',
      'data_origin':'synthetic','chunker_version':config['chunker_version'],'count':len(chunks)})
    save(output/'evaluation_status.json',{
      'status':'NOT_EVALUATED',
      'reason':'Corpus/index creation is not a reviewed retrieval benchmark',
      'requires_reviewed_questions':True,
      'required_methods':['keyword','dense'],
    })
    return chunks


def evaluate(chunks,questions_path,config,output,split='dev',dense=False,index_path=None,reviewed=False,freeze_approval_path=None):
    config_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    if split not in ['dev','test']:
        raise ValueError('INVALID_SPLIT')
    if split=='test':
        if freeze_approval_path is None:
            raise ValueError('FROZEN_RAG_CONFIG_APPROVAL_REQUIRED')
        approval=load(freeze_approval_path)
        if (approval.get('approved') is not True or not approval.get('owner')
                or approval.get('config_sha256')!=config_hash
                or approval.get('questions_sha256')!=sha(questions_path)):
            raise ValueError('FROZEN_RAG_CONFIG_AND_QUESTIONS_APPROVAL_REQUIRED')
    all_questions=read_jsonl(questions_path)
    if not reviewed:
        raise ValueError('HUMAN_GOLD_REVIEW_REQUIRED: drafted questions are not an independent benchmark')
    validate_benchmark_questions(all_questions, chunks, require_reviewed=True)
    questions=[q for q in all_questions if q['split']==split]
    if Path(output).exists():
        raise ValueError('EVALUATION_OUTPUT_EXISTS')
    if split=='test':
        marker=Path(freeze_approval_path).with_name('FINAL_RAG_TEST_STARTED.json')
        with marker.open('x',encoding='utf-8') as stream:
            json.dump({'config_sha256':config_hash,'questions_sha256':sha(questions_path),'status':'started'},stream)
    methods=['keyword']+(['dense'] if dense else [])
    retriever=None
    if dense:
        retriever=DenseRetriever(index_path,config);retriever.index(chunks)
    predictions=[];summary={}
    for method in methods:
        hits=[];latencies=[];scope_violations=0
        for question in questions:
            start=time.perf_counter()
            args=(question['question'],question['expected_scope'],question['as_of'],config['retrieval_k'])
            results=lexical_search(chunks,*args) if method=='keyword' else retriever.search(*args)
            elapsed=(time.perf_counter()-start)*1000;latencies.append(elapsed)
            found=[r['chunk']['chunk_id'] for r in results]
            if question['expected_behavior']=='answerable':
                hits.append(bool(set(found)&set(question['gold_chunk_ids'])))
            scope_violations+=sum(r['chunk']['scope']!=question['expected_scope'] for r in results)
            predictions.append({'question_id':question['question_id'],'split':split,'method':method,
              'retrieved_ids':found,'scores':[r['score'] for r in results],'latency_ms':elapsed,
              'response':evidence_response(results,question['question']),'corpus_version':config['corpus_version'],
              'config_sha256':config_hash,
              'answer_correctness':None,'citation_support_precision':None,'token_usage':None,'cost':None})
        summary[method]={'hit_at_5':sum(hits)/len(hits) if hits else None,'answerable_count':len(hits),
          'latency_p50_ms':float(np.percentile(latencies,50)),'latency_p95_ms':float(np.percentile(latencies,95)),
          'scope_violations':scope_violations,'generation_evaluated':False,'abstention_quality':None}
    Path(output).mkdir(parents=True)
    jsonl(Path(output)/'rag_predictions.jsonl',predictions)
    save(Path(output)/'metrics.json',summary)
    save(Path(output)/'rag_config.json',config)
    save(Path(output)/'evaluation_status.json',{
      'status':'DEV_EVALUATED' if split=='dev' else 'FINAL_TEST_EVALUATED',
      'reviewed_questions':True,
      'methods':methods,
      'questions_sha256':sha(questions_path),
      'config_sha256':config_hash,
    })
    return summary
