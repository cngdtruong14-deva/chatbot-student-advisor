"""Shared offline/runtime retrieval. No LLM, database credentials, or executable document instructions."""
import hashlib
import math
import re
from collections import Counter
from datetime import date


from .legal_chunker import chunk_hierarchical_legal, LegalChunk


def tokens(text):
    return re.findall(r'\w+',text.lower(),flags=re.UNICODE)


def chunk_markdown(text, *, document_id, version_id, scope, source, valid_from, max_chars=1600):
    if not text.strip() or max_chars<200:
        raise ValueError('INVALID_DOCUMENT')
    date.fromisoformat(valid_from)
    chunks=[]
    current_page = None
    for index,paragraph in enumerate(re.split(r'\n\s*\n',text.strip())):
        page_match = re.match(r'^##\s+Trang\s+(\d+)', paragraph.strip(), flags=re.IGNORECASE)
        if page_match:
            current_page = page_match.group(1)
        if len(paragraph)>max_chars:
            raise ValueError('PARAGRAPH_TOO_LONG: split at source boundaries and remap gold evidence')
        digest=hashlib.sha256(paragraph.encode()).hexdigest()
        identity=hashlib.sha256(f'{document_id}|{version_id}|{index}|{digest}'.encode()).hexdigest()
        section_label = f"Trang {current_page}, Đoạn {index+1}" if current_page else str(index+1)
        chunks.append({'chunk_id':identity,'document_id':document_id,'version_id':version_id,'scope':scope,
          'source':source,'valid_from':valid_from,'valid_until':'9999-12-31','section':section_label,
          'text':paragraph,'text_hash':digest,'data_origin':'synthetic','status':'approved_demo',
          'page_number':int(current_page) if current_page else None, 'locator_label':section_label})
    return chunks


def applicable(chunks,scope,as_of):
    when = date.fromisoformat(as_of) if isinstance(as_of, str) else (as_of or date.today())
    return [c for c in chunks if c['scope']==scope and c.get('status', 'approved_demo') in ('approved_demo', 'reviewed', 'active', 'test_only')
            and date.fromisoformat(c['valid_from'])<=when<date.fromisoformat(c['valid_until'])]


def lexical_search(chunks,query,scope,as_of,k=5):
    documents=applicable(chunks,scope,as_of)
    if not documents or not tokens(query):
        return []
    terms=set(tokens(query)); counts=[Counter(tokens(c['text'])) for c in documents]
    avg=sum(sum(c.values()) for c in counts)/len(counts)
    scores=[]
    for doc,count in zip(documents,counts):
        score=0.0
        for term in terms:
            df=sum(term in c for c in counts)
            idf=math.log(1+(len(documents)-df+.5)/(df+.5))
            tf=count[term]
            score+=idf*(tf*2.5)/(tf+1.5*(.25+.75*sum(count.values())/max(avg,1)))
        if score>0:
            scores.append({'chunk':doc,'score':score})
    return sorted(scores,key=lambda r:(-r['score'],r['chunk']['chunk_id']))[:k]


class DenseRetriever:
    """Chroma PersistentClient, single writer. Rebuild from chunks, never copy a live index."""
    def __init__(self,path,config):
        import chromadb
        from chromadb.config import Settings
        from sentence_transformers import SentenceTransformer
        if not re.fullmatch('[a-f0-9]{40}',config.get('embedding_revision','')):
            raise ValueError('PIN_EMBEDDING_REVISION')
        self.config=config
        self.embedder=SentenceTransformer(config['embedding_model'],revision=config['embedding_revision'],trust_remote_code=False)
        self.client=chromadb.PersistentClient(path=str(path),settings=Settings(anonymized_telemetry=False))
        self.collection=None

    def index(self,chunks):
        corpus_hash=hashlib.sha256(''.join(c['chunk_id'] for c in chunks).encode()).hexdigest()
        config_hash=hashlib.sha256(str(sorted(self.config.items())).encode()).hexdigest()
        name='demo-'+corpus_hash[:16]+'-'+config_hash[:12]
        collection=self.client.get_or_create_collection(name=name,embedding_function=None,metadata={'hnsw:space':'cosine','corpus_hash':corpus_hash})
        if collection.count() not in (0,len(chunks)):
            raise ValueError('PARTIAL_INDEX: use a new version; do not activate')
        if collection.count()==0:
            vectors=self.embedder.encode(['passage: '+c['text'] for c in chunks],normalize_embeddings=True).tolist()
            collection.add(ids=[c['chunk_id'] for c in chunks],embeddings=vectors,documents=[c['text'] for c in chunks],
              metadatas=[{k:v for k,v in c.items() if k!='text'} for c in chunks])
        if collection.count()!=len(chunks):
            raise ValueError('INDEX_INCOMPLETE')
        self.collection=collection
        self.chunks={c['chunk_id']:c for c in chunks}
        return {'collection':name,'corpus_hash':corpus_hash,'embedding_dimension':self.embedder.get_sentence_embedding_dimension()}

    def search(self,query,scope,as_of,k=5):
        allowed=applicable(list(self.chunks.values()),scope,as_of)
        if not allowed:
            return []
        vector=self.embedder.encode(['query: '+query],normalize_embeddings=True).tolist()
        result=self.collection.query(query_embeddings=vector,where={'chunk_id':{'$in':[c['chunk_id'] for c in allowed]}},n_results=min(k,len(allowed)),include=['distances'])
        return [{'chunk':self.chunks[cid],'score':1-float(distance)} for cid,distance in zip(result['ids'][0],result['distances'][0])]


class GenerationUnavailable:
    """Future provider adapter point. API key is never stored in corpus/config/export."""
    def generate(self,query,evidence):
        return {'status':'provider_unavailable','answer':None,'claims':[]}


def evidence_response(results,query,provider=None):
    # Similarity alone is not proof that a question can be answered. No guessed cutoff threshold.
    generated=(provider or GenerationUnavailable()).generate(query,results)
    completed=generated['status']=='completed' and bool(generated['answer']) and bool(generated['claims'])
    return {'status':'answered' if completed else 'insufficient_evidence','retrieval_status':'candidates_found' if results else 'not_found',
      'answer':generated['answer'],'generation_status':generated['status'],'claims':generated['claims'],
      'citations':[{'chunk_id':r['chunk']['chunk_id'],'version_id':r['chunk']['version_id'],
        'source':r['chunk']['source'],'section':r['chunk'].get('section', ''),'excerpt':r['chunk']['text'],
        'data_origin':r['chunk'].get('data_origin', 'user_provided_institutional_document'),
        'page_number':r['chunk'].get('page_number'),
        'locator_label':r['chunk'].get('locator_label') or r['chunk'].get('section'),
        'major':r['chunk'].get('major'),'cohort':r['chunk'].get('cohort'),
        'effective_from':r['chunk'].get('effective_from'),'effective_until':r['chunk'].get('effective_until'),
        'is_effective_date_verified':r['chunk'].get('is_effective_date_verified', False)} for r in results],
      'note':'Câu trả lời do LLM tổng hợp từ các trích đoạn được dẫn nguồn.' if completed else
               'Đây là các trích đoạn tài liệu ứng viên, chưa phải câu trả lời đã được đánh giá đủ bằng chứng.'}
