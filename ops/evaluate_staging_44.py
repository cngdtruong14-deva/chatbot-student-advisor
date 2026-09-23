"""Evaluate Quality and Retrieval Capability of the 44 staging documents.
Offline, isolated, read-only with respect to live DB and live vectorstore.
"""
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

# Add backend and packages to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / 'backend'))
sys.path.insert(0, str(REPO_ROOT / 'packages/advisor_core/src'))

from advisor_core.rag import tokens, chunk_markdown, lexical_search

STAGING_DIR = REPO_ROOT / 'artifacts/phase_b/project_extracted_44'
CONFIG = {
    'embedding_model': 'intfloat/multilingual-e5-small',
    'embedding_revision': '614241f622f53c4eeff9890bdc4f31cfecc418b3'
}

ACADEMIC_KEYWORDS = [
    'tín chỉ', 'học phần', 'điểm', 'sinh viên', 'tốt nghiệp', 'quy chế',
    'quy định', 'khoa', 'trường', 'đào tạo', 'khen thưởng', 'kỷ luật',
    'học bổng', 'rèn luyện', 'học phí', 'nghiên cứu', 'chương trình',
    'điều kiện', 'thời gian', 'kết quả'
]

BENCHMARK_QUERIES = [
    {
        'query_id': 'Q01',
        'query': 'Chương trình đào tạo ngành Công nghệ thông tin có bao nhiêu tín chỉ và thời gian đào tạo bao lâu?',
        'target_substr': 'Công nghệ thông tin',
        'expected_source_fragment': 'CTDT Công nghệ thông tin'
    },
    {
        'query_id': 'Q02',
        'query': 'Chương trình đào tạo Hệ thống thông tin yêu cầu bao nhiêu tín chỉ?',
        'target_substr': 'Hệ thống thông tin',
        'expected_source_fragment': 'CTDT Hệ thống thông tin'
    },
    {
        'query_id': 'Q03',
        'query': 'Chuẩn đầu ra Ngoại ngữ đối với sinh viên đại học chính quy áp dụng chứng chỉ gì?',
        'target_substr': 'chuẩn đầu ra',
        'expected_source_fragment': 'Chuẩn đầu ra Ngoại ngữ'
    },
    {
        'query_id': 'Q04',
        'query': 'Chuẩn đầu ra Tin học áp dụng cho sinh viên các khóa gồm những chứng chỉ nào?',
        'target_substr': 'tin học',
        'expected_source_fragment': 'Chuẩn đầu ra Tin học'
    },
    {
        'query_id': 'Q05',
        'query': 'Quy chế và hướng dẫn đánh giá Điểm rèn luyện sinh viên gồm những khung điểm nào?',
        'target_substr': 'rèn luyện',
        'expected_source_fragment': 'Đánh giá Điểm rèn luyện'
    },
    {
        'query_id': 'Q06',
        'query': 'Quy định về xét, cấp học bổng khuyến khích học tập cho sinh viên có tiêu chuẩn gì?',
        'target_substr': 'học bổng',
        'expected_source_fragment': 'Quy định xét, cấp HB KKHT'
    },
    {
        'query_id': 'Q07',
        'query': 'Nội quy học đường quy định sinh viên không được làm những hành vi gì?',
        'target_substr': 'nội quy',
        'expected_source_fragment': 'Nội quy học đường'
    },
    {
        'query_id': 'Q08',
        'query': 'Quy định tham gia thi sinh viên giỏi, thi Olympic sinh viên được hỗ trợ gì?',
        'target_substr': 'Olympic',
        'expected_source_fragment': 'Quy định thi SVG, Olympic'
    },
    {
        'query_id': 'Q09',
        'query': 'Quy định về miễn giảm học phí cho sinh viên theo diện chính sách?',
        'target_substr': 'học phí',
        'expected_source_fragment': 'Miễn, giảm HP'
    },
    {
        'query_id': 'Q10',
        'query': 'Mẫu đơn xin phúc khảo bài thi kết thúc học phần cần thông tin gì?',
        'target_substr': 'phúc khảo',
        'expected_source_fragment': 'ĐƠN XIN PHÚC KHẢO BÀI THI'
    },
    {
        'query_id': 'Q11',
        'query': 'Mẫu đơn xin học lại, học cải thiện điểm học phần như thế nào?',
        'target_substr': 'học cải thiện',
        'expected_source_fragment': 'Đơn xin học lại - học cải thiện'
    },
    {
        'query_id': 'Q12',
        'query': 'Mẫu đơn xin tiếp tục học tập sau khi hết thời gian tạm ngừng?',
        'target_substr': 'tiếp tục học tập',
        'expected_source_fragment': 'Đơn xin tiếp tục học tập'
    },
    {
        'query_id': 'Q13',
        'query': 'Đơn xin đăng ký lại học phần cho sinh viên không đạt?',
        'target_substr': 'đăng ký lại',
        'expected_source_fragment': 'Đơn xin đăng ký lại học phần'
    },
    {
        'query_id': 'Q14',
        'query': 'Đơn đề nghị cấp thẻ sinh viên làm lại thẻ bị mất?',
        'target_substr': 'thẻ sinh viên',
        'expected_source_fragment': 'ĐƠN ĐỀ NGHỊ CẤP THẺ SINH VIÊN'
    },
    {
        'query_id': 'Q15',
        'query': 'Sinh viên UTT được hỗ trợ gì khi tham gia hoạt động nghiên cứu khoa học?',
        'target_substr': 'nghiên cứu khoa học',
        'expected_source_fragment': 'Sinh viên UTT được hỗ trợ gì'
    },
    {
        'query_id': 'Q16',
        'query': '8 bước cơ bản bắt đầu một dự án nghiên cứu khoa học của sinh viên?',
        'target_substr': 'NCKH',
        'expected_source_fragment': '8 bước cơ bản bắt đầu một dự án NCKH'
    },
    {
        'query_id': 'Q17',
        'query': 'Sinh viên nghiên cứu khoa học khi nào nên bắt đầu và lợi ích là gì?',
        'target_substr': 'nghiên cứu khoa học',
        'expected_source_fragment': 'Sinh viên nghiên cứu khoa học_ Khi nào nên bắt đầu_'
    },
    {
        'query_id': 'Q18',
        'query': 'Chương trình đào tạo Công nghệ kỹ thuật cơ điện tử đào tạo khối lượng bao nhiêu?',
        'target_substr': 'cơ điện tử',
        'expected_source_fragment': 'CTDT Công nghệ kỹ thuật cơ điện tử'
    },
    {
        'query_id': 'Q19',
        'query': 'Chương trình đào tạo Công nghệ kỹ thuật điện tử viễn thông có những môn gì?',
        'target_substr': 'điện tử - viễn thông',
        'expected_source_fragment': 'CTDT Công nghệ kỹ thuật điện tử - viễn thông'
    },
    {
        'query_id': 'Q20',
        'query': 'Hướng dẫn sinh viên khai báo thông tin hồ sơ sinh viên trực tuyến?',
        'target_substr': 'hồ sơ',
        'expected_source_fragment': 'HDĐĂNG NHẬP VÀ KHAI BÁO THÔNG TIN HỒ SƠ SV'
    }
]


def rrf(rank_lists, k=60):
    """Reciprocal Rank Fusion."""
    scores = {}
    item_map = {}
    for rlist in rank_lists:
        for rank, item in enumerate(rlist, 1):
            cid = item['chunk']['chunk_id']
            item_map[cid] = item['chunk']
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank))
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [{'chunk': item_map[cid], 'score': score} for cid, score in ranked]


def main():
    t0 = time.time()
    print("=================================================================")
    print("PHASE B: STAGING 44 DOCUMENTS QUALITY & RETRIEVAL EVALUATION")
    print("=================================================================")

    # 1. Load results.json to get the exact 44 extracted documents
    results_path = STAGING_DIR / 'results.json'
    if not results_path.exists():
        print(f"ERROR: {results_path} not found!")
        return

    with open(results_path, 'r', encoding='utf-8') as f:
        all_results = json.load(f)

    extracted_records = [r for r in all_results if r['status'] == 'extracted_pending_quality_review']
    print(f"Found {len(extracted_records)} documents marked 'extracted_pending_quality_review'.")

    # 2. Analyze Document Quality
    print("\n--- 1. Evaluating Extraction Quality across 44 Documents ---")
    quality_records = []
    total_chars = 0
    total_pages = 0
    all_chunks = []

    for idx, rec in enumerate(extracted_records, 1):
        sid = rec['source_id']
        title = rec['title']
        doc_file = STAGING_DIR / rec['output_file']
        doc_data = json.loads(doc_file.read_text(encoding='utf-8'))

        content = doc_data.get('content', '')
        fmt = doc_data.get('format', 'unknown')
        p_count = doc_data.get('page_count') or 1
        c_count = doc_data.get('character_count') or len(content)
        warnings = doc_data.get('warnings', [])

        total_chars += c_count
        total_pages += p_count

        # Quality metrics
        # a. Keyword coverage
        content_lower = content.lower()
        matched_keywords = [kw for kw in ACADEMIC_KEYWORDS if kw in content_lower]
        kw_density = round(len(matched_keywords) / len(ACADEMIC_KEYWORDS) * 100, 1)

        # b. Binary / corrupted character check
        replacement_chars = content.count('\ufffd')
        null_chars = content.count('\x00')
        is_clean = (replacement_chars == 0 and null_chars == 0)

        # c. Density: chars per page
        chars_per_page = round(c_count / max(p_count, 1), 1)

        # d. Page locators check
        page_locators = re.findall(r'^##\s+Trang\s+(\d+)', content, flags=re.MULTILINE)

        q_item = {
            'index': idx,
            'source_id': sid,
            'title': title,
            'format': fmt,
            'page_count': p_count,
            'character_count': c_count,
            'chars_per_page': chars_per_page,
            'matched_keywords_count': len(matched_keywords),
            'keyword_coverage_pct': kw_density,
            'clean_text_check': is_clean,
            'warnings': warnings,
            'has_page_locators': len(page_locators) > 0,
            'page_locators_count': len(page_locators)
        }
        quality_records.append(q_item)

        # Chunking: canonical paragraph splitting
        paragraphs = content.split('\n\n')
        normalized = '\n\n'.join(p[i:i+1400] for p in paragraphs for i in range(0, len(p), 1400))
        doc_chunks = chunk_markdown(
            normalized,
            document_id=sid,
            version_id=f"v_{sid[:8]}",
            scope='demo_academic',
            source=f"institutional:{title}",
            valid_from='2026-01-01'
        )
        for c in doc_chunks:
            c['document_title'] = title
        all_chunks.extend(doc_chunks)

    print(f"Total Pages Extracted: {total_pages}")
    print(f"Total Characters: {total_chars:,}")
    print(f"Average Chars/Page: {round(total_chars / max(total_pages, 1), 1):,}")
    print(f"Total Chunks Produced: {len(all_chunks)}")
    print(f"All 44 documents passed clean text validation: {all(r['clean_text_check'] for r in quality_records)}")

    # 3. Setup Isolated Vectorstore & Dense Retrieval
    print("\n--- 2. Setting Up Isolated Dense & Lexical Retrievers ---")
    import chromadb
    from sentence_transformers import SentenceTransformer

    print("Loading embedding model intfloat/multilingual-e5-small from cache...")
    hf_cache = REPO_ROOT / 'vectorstore/hf'
    os.environ['HF_HOME'] = str(hf_cache)
    embedder = SentenceTransformer(
        CONFIG['embedding_model'],
        revision=CONFIG['embedding_revision'],
        local_files_only=True,
        device='cpu'
    )

    chroma_client = chromadb.EphemeralClient()
    collection = chroma_client.create_collection(
        name='staging_44_test',
        metadata={'hnsw:space': 'cosine'}
    )

    print(f"Encoding {len(all_chunks)} chunks for dense indexing (batch size 64)...")
    batch_size = 64
    for i in range(0, len(all_chunks), batch_size):
        b_chunks = all_chunks[i:i+batch_size]
        texts = ['passage: ' + c['text'] for c in b_chunks]
        vecs = embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()
        collection.add(
            ids=[c['chunk_id'] for c in b_chunks],
            embeddings=vecs,
            documents=[c['text'] for c in b_chunks],
            metadatas=[{'document_title': c['document_title'], 'source_id': c['document_id'], 'section': c['section']} for c in b_chunks]
        )
    print(f"Dense Indexing Complete: {collection.count()} vectors stored.")

    # 4. Execute Retrieval Benchmark
    print("\n--- 3. Running 20-Query Retrieval Benchmark across 44 Staging Documents ---")
    benchmark_results = []
    hits_top1_dense = 0
    hits_top3_dense = 0
    hits_top5_dense = 0

    hits_top1_lexical = 0
    hits_top3_lexical = 0
    hits_top5_lexical = 0

    hits_top1_hybrid = 0
    hits_top3_hybrid = 0
    hits_top5_hybrid = 0

    rr_dense = []
    rr_lexical = []
    rr_hybrid = []

    for bq in BENCHMARK_QUERIES:
        qid = bq['query_id']
        query = bq['query']
        target_frag = bq['expected_source_fragment'].lower()

        # A. Lexical search (BM25)
        lex_results = lexical_search(all_chunks, query, scope='demo_academic', as_of='2026-09-06', k=10)

        # B. Dense search
        q_vec = embedder.encode(['query: ' + query], normalize_embeddings=True).tolist()
        chroma_res = collection.query(
            query_embeddings=q_vec,
            n_results=10,
            include=['distances', 'metadatas', 'documents']
        )
        dense_results = []
        for cid, dist, meta, doc_txt in zip(chroma_res['ids'][0], chroma_res['distances'][0], chroma_res['metadatas'][0], chroma_res['documents'][0]):
            chunk_obj = next(c for c in all_chunks if c['chunk_id'] == cid)
            dense_results.append({
                'chunk': chunk_obj,
                'score': round(1.0 - float(dist), 4),
                'cosine_dist': round(float(dist), 4)
            })

        # C. Hybrid RRF
        hybrid_results = rrf([dense_results, lex_results], k=60)[:10]

        # Helper to find rank of target
        def get_target_rank(rlist):
            for rank, r in enumerate(rlist, 1):
                t = r['chunk']['document_title'].lower()
                if target_frag in t:
                    return rank
            return 999

        dense_rank = get_target_rank(dense_results)
        lex_rank = get_target_rank(lex_results)
        hyb_rank = get_target_rank(hybrid_results)

        # Scoring
        if dense_rank == 1: hits_top1_dense += 1
        if dense_rank <= 3: hits_top3_dense += 1
        if dense_rank <= 5: hits_top5_dense += 1
        rr_dense.append(1.0 / dense_rank if dense_rank <= 10 else 0.0)

        if lex_rank == 1: hits_top1_lexical += 1
        if lex_rank <= 3: hits_top3_lexical += 1
        if lex_rank <= 5: hits_top5_lexical += 1
        rr_lexical.append(1.0 / lex_rank if lex_rank <= 10 else 0.0)

        if hyb_rank == 1: hits_top1_hybrid += 1
        if hyb_rank <= 3: hits_top3_hybrid += 1
        if hyb_rank <= 5: hits_top5_hybrid += 1
        rr_hybrid.append(1.0 / hyb_rank if hyb_rank <= 10 else 0.0)

        top_dense_title = dense_results[0]['chunk']['document_title'] if dense_results else 'NONE'
        top_dense_score = dense_results[0]['score'] if dense_results else 0.0
        top_excerpt = (dense_results[0]['chunk']['text'][:120] + '...') if dense_results else ''

        b_entry = {
            'query_id': qid,
            'query': query,
            'target_document': bq['expected_source_fragment'],
            'dense_rank': dense_rank if dense_rank <= 10 else None,
            'lexical_rank': lex_rank if lex_rank <= 10 else None,
            'hybrid_rank': hyb_rank if hyb_rank <= 10 else None,
            'top_retrieved_title': top_dense_title,
            'top_retrieved_similarity': top_dense_score,
            'top_retrieved_excerpt': top_excerpt.replace('\n', ' ')
        }
        benchmark_results.append(b_entry)

        status_str = "PASS (Rank 1)" if hyb_rank == 1 else (f"PASS (Rank {hyb_rank})" if hyb_rank <= 3 else f"FAIL (Rank {hyb_rank})")
        print(f"[{qid}] {query[:55]}... -> {status_str} | Target: {bq['expected_source_fragment']} | Dense: R{dense_rank}, Lex: R{lex_rank}, Hyb: R{hyb_rank}")

    num_q = len(BENCHMARK_QUERIES)
    mrr_dense = round(sum(rr_dense) / num_q, 4)
    mrr_lexical = round(sum(rr_lexical) / num_q, 4)
    mrr_hybrid = round(sum(rr_hybrid) / num_q, 4)

    print("\n--- Benchmark Summary Statistics ---")
    print(f"Dense (E5 Small)  : Top-1 = {hits_top1_dense}/{num_q} ({hits_top1_dense/num_q*100:.1f}%), Top-3 = {hits_top3_dense}/{num_q} ({hits_top3_dense/num_q*100:.1f}%), MRR = {mrr_dense:.4f}")
    print(f"Lexical (BM25)    : Top-1 = {hits_top1_lexical}/{num_q} ({hits_top1_lexical/num_q*100:.1f}%), Top-3 = {hits_top3_lexical}/{num_q} ({hits_top3_lexical/num_q*100:.1f}%), MRR = {mrr_lexical:.4f}")
    print(f"Hybrid (RRF)      : Top-1 = {hits_top1_hybrid}/{num_q} ({hits_top1_hybrid/num_q*100:.1f}%), Top-3 = {hits_top3_hybrid}/{num_q} ({hits_top3_hybrid/num_q*100:.1f}%), MRR = {mrr_hybrid:.4f}")

    # 5. Output Reports
    output_quality_file = REPO_ROOT / 'artifacts/phase_b/staging_44_quality_report.json'
    output_bench_file = REPO_ROOT / 'artifacts/phase_b/staging_44_retrieval_benchmark.json'

    quality_summary = {
        'evaluation_date': date.today().isoformat(),
        'total_documents': len(extracted_records),
        'total_pages': total_pages,
        'total_characters': total_chars,
        'average_characters_per_page': round(total_chars / max(total_pages, 1), 1),
        'total_chunks_generated': len(all_chunks),
        'chunk_size_stats': {
            'min_chars': min(len(c['text']) for c in all_chunks),
            'max_chars': max(len(c['text']) for c in all_chunks),
            'avg_chars': round(sum(len(c['text']) for c in all_chunks) / len(all_chunks), 1)
        },
        'clean_text_check_all_pass': all(r['clean_text_check'] for r in quality_records),
        'documents': quality_records
    }
    with open(output_quality_file, 'w', encoding='utf-8') as f:
        json.dump(quality_summary, f, ensure_ascii=False, indent=2)
    print(f"\nWritten quality report to {output_quality_file}")

    benchmark_summary = {
        'evaluation_date': date.today().isoformat(),
        'embedding_model': CONFIG['embedding_model'],
        'benchmark_queries_count': num_q,
        'metrics': {
            'dense': {
                'top1_hit_rate': round(hits_top1_dense / num_q, 4),
                'top3_hit_rate': round(hits_top3_dense / num_q, 4),
                'top5_hit_rate': round(hits_top5_dense / num_q, 4),
                'mrr': mrr_dense
            },
            'lexical': {
                'top1_hit_rate': round(hits_top1_lexical / num_q, 4),
                'top3_hit_rate': round(hits_top3_lexical / num_q, 4),
                'top5_hit_rate': round(hits_top5_lexical / num_q, 4),
                'mrr': mrr_lexical
            },
            'hybrid_rrf': {
                'top1_hit_rate': round(hits_top1_hybrid / num_q, 4),
                'top3_hit_rate': round(hits_top3_hybrid / num_q, 4),
                'top5_hit_rate': round(hits_top5_hybrid / num_q, 4),
                'mrr': mrr_hybrid
            }
        },
        'queries': benchmark_results
    }
    with open(output_bench_file, 'w', encoding='utf-8') as f:
        json.dump(benchmark_summary, f, ensure_ascii=False, indent=2)
    print(f"Written retrieval benchmark results to {output_bench_file}")

    print("In-memory ephemeral collection released.")
    print(f"Evaluation completed in {round(time.time() - t0, 2)}s.")


if __name__ == '__main__':
    main()
