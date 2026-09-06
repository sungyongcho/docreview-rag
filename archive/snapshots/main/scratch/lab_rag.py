from __future__ import annotations

from typing import Any, TypedDict, cast

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Metadata
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from sentence_transformers import SentenceTransformer


class PolicyDocument(TypedDict):
    id: str
    title: str
    content: str
    category: str


class PolicyChunk(TypedDict):
    id: str
    title: str
    content: str
    category: str
    source_doc: str


class SearchResult(TypedDict):
    id: str
    content: str
    metadata: Metadata
    similarity: float


def load_and_chunk_documents() -> list[PolicyChunk]:
    print("====================document loading & chunking====================")

    policy_documents: list[PolicyDocument] = [
        {
            "id": "policy_001",
            "title": "Home Office Equipment Reimbursement",
            "content": "Employees working from home may claim up to $500 per year for office equipment including desks, chairs, monitors, and computer accessories. Receipts must be submitted within 30 days of purchase. This policy applies to full-time remote workers only. The equipment must be used primarily for work purposes and should be ergonomic and suitable for a professional home office environment.",
            "category": "reimbursement",
        },
        {
            "id": "policy_002",
            "title": "Travel Expense Guidelines",
            "content": "Business travel expenses are reimbursable when pre-approved by your manager. Meals are covered up to $50 per day, hotel stays up to $200 per night. All receipts must be submitted within 14 days of return. International travel requires additional approval from the department head. Travel insurance is mandatory for all business trips exceeding 7 days.",
            "category": "travel",
        },
        {
            "id": "policy_003",
            "title": "Remote Work Furniture Policy",
            "content": "Remote employees may purchase ergonomic furniture for their home office setup. This includes standing desks, ergonomic chairs, and monitor arms. Maximum reimbursement is $300 per item with manager approval required. All furniture must meet ergonomic standards and be purchased from approved vendors. Receipts must be submitted within 45 days of purchase.",
            "category": "reimbursement",
        },
        {
            "id": "policy_004",
            "title": "Equipment and Supplies Reimbursement",
            "content": "Work-related equipment and supplies purchased for home office use are eligible for reimbursement. This covers laptops, monitors, keyboards, mice, and other computer peripherals. Submit expense reports with receipts for approval. Equipment must be used for work purposes and should be compatible with company systems. Annual limit is $1000 per employee.",
            "category": "reimbursement",
        },
        {
            "id": "policy_005",
            "title": "Vacation and PTO Policy",
            "content": "Full-time employees accrue 15 days of paid time off per year. Vacation requests must be submitted at least 2 weeks in advance. Unused PTO does not roll over to the next year. Emergency leave can be taken with manager approval. Sick leave is separate from vacation time and does not count against PTO balance.",
            "category": "benefits",
        },
    ]

    print(f"loaded {len(policy_documents)} policy documents")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=200,
        chunk_overlap=50,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )

    all_chunks: list[PolicyChunk] = []
    for doc in policy_documents:
        chunks = text_splitter.split_text(doc["content"])
        for i, chunk in enumerate(chunks):
            all_chunks.append(
                {
                    "id": f"{doc['id']}_chunk_{i}",
                    "title": doc["title"],
                    "content": chunk,
                    "category": doc["category"],
                    "source_doc": doc["id"],
                }
            )

    print(f"✂️ Created {len(all_chunks)} chunks from {len(policy_documents)} documents")
    print(
        f"📏 Average chunk size: {sum(len(chunk['content']) for chunk in all_chunks) // len(all_chunks)} characters"
    )
    print("====================document loading & chunking====================")

    return all_chunks


def setup_vector_database(chunks: list[PolicyChunk]) -> Collection:
    print("======================vector database setup========================")

    client = chromadb.Client()

    try:
        collection = client.create_collection(
            name="techcorp_policies",
            metadata={"hnsw:space": "cosine"},
        )
    except Exception:
        collection = client.get_collection("techcorp_policies")

    print(f"🗄️ Created collection: {collection.name}")
    print("📊 Similarity metric: cosine")

    ids: list[str] = [chunk["id"] for chunk in chunks]
    documents: list[str] = [chunk["content"] for chunk in chunks]
    metadatas: list[Metadata] = [
        {
            "title": chunk["title"],
            "category": chunk["category"],
            "source": chunk["source_doc"],
        }
        for chunk in chunks
    ]

    if collection.count() == 0:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        print(f"✅ Stored {len(chunks)} chunks in vector database")
    else:
        print(f"✅ Collection already contains {collection.count()} chunks")

    print(f"📈 Collection count: {collection.count()}")

    print("======================vector database setup========================")
    return collection


def process_user_query(query: str) -> tuple[SentenceTransformer, Any]:
    print("=========================query processing==========================")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"🤖 Using model: {model}")
    print(f"📐 Embedding dimensions: {model.get_embedding_dimension()}")

    # preprocessing
    cleaned_query = query.lower().strip()
    print(f"📝 Original query: '{query}'")
    print(f"🧹 Cleaned query: '{cleaned_query}'")

    query_embedding = model.encode([cleaned_query])
    print(f"🔢 Query embedding shape: {query_embedding.shape}")
    print(f"📊 Embedding sample: {query_embedding[0][:5]}...")

    print("=========================query processing==========================")
    return model, query_embedding[0]


def search_vector_database(
    collection: Collection, query_embedding: Any, top_k: int = 3
) -> list[SearchResult]:
    print("==========================vector search============================")

    results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    distance_batches = results["distances"]
    document_batches = results["documents"]
    metadata_batches = results["metadatas"]
    if distance_batches is None or document_batches is None or metadata_batches is None:
        raise RuntimeError(
            "Chroma query did not return documents, metadatas, and distances"
        )

    result_ids = results["ids"][0]
    distances = cast(list[float], distance_batches[0])
    documents = cast(list[str], document_batches[0])
    metadata_rows = cast(list[Metadata], metadata_batches[0])

    print(f"🎯 Searching for top {top_k} results")
    print(f"📊 Found {len(result_ids)} relevant chunks")

    search_results: list[SearchResult] = []
    for i, (doc_id, distance, content, metadata) in enumerate(
        zip(result_ids, distances, documents, metadata_rows, strict=True)
    ):
        similarity = 1 - distance
        search_results.append(
            {
                "id": doc_id,
                "content": content,
                "metadata": metadata,
                "similarity": similarity,
            }
        )

        title = metadata.get("title", "unknown")
        category = metadata.get("category", "unknown")
        print(f"\n{i + 1}. {title} (Category: {category})")
        print(f"   Similarity: {similarity:.3f}")
        print(f"   Content: {content[:100]}...")

    print("==========================vector search============================")
    return search_results


def augment_prompt_with_context(query: str, search_results: list[dict]) -> str:
    print("=====================context augumentation=========================")
    context_parts = []
    for i, result in enumerate(search_results, 1):
        context_parts.append(
            f"Source: {i}: {result['metadata']['title']}\n{result['content']}"
        )
    context = "\n\n".join(context_parts)

    print(f"📄 Assembled context from {len(search_results)} sources")
    print(f"📏 Context length: {len(context)} characters")

    augmented_prompt = f"""
Based on the following company policies, answer the user's question.

POLICIES:
{context}

QUESTION: {query}

Please provide a clear, accurate answer based on the policies above.
If the information is not available in the policies, say so.
Include relevant policy details and any limitations or requirements.
"""

    print(f"📝 Augmented prompt length: {len(augmented_prompt)} characters")
    print(
        f"🔗 Context sources: {[result['metadata']['title'] for result in search_results]}"
    )

    print("=====================context augumentation=========================")
    return augmented_prompt


def generate_response(augmented_prompt: str, model: str = "gpt-4.1-mini") -> str:
    print("======================response generation==========================")

    # OpenAI 클라이언트. OPENAI_API_KEY 환경변수를 자동으로 읽는다.
    client = OpenAI()

    response = client.chat.completions.create(
        model=model,
        temperature=0,  # 결정적에 가깝게 (근거 기반 답이라 창의성 불필요)
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a company policy assistant. Answer ONLY using the "
                    "policies provided in the user message. If the answer is not "
                    "contained in them, say you don't have that information. "
                    "Do not use outside knowledge."
                ),
            },
            {"role": "user", "content": augmented_prompt},
        ],
    )

    answer = response.choices[0].message.content
    if answer is None:
        raise RuntimeError("OpenAI response did not contain text content")

    usage = response.usage
    if usage is None:
        print(f"✅ model={model} tokens=unknown")
    else:
        print(
            f"✅ model={model} tokens={usage.total_tokens} "
            f"(prompt={usage.prompt_tokens}, out={usage.completion_tokens})"
        )

    return answer


if __name__ == "__main__":
    q = "How much can I claim for home office equipment?"
    chunks = load_and_chunk_documents()  # 섹션1 → 청크 개수/평균 길이 출력
    print("CHECK1 chunks =", len(chunks))
    print(chunks[0])
    collection = setup_vector_database(chunks)  # 섹션2 → count == len(chunks) 인지
    print("CHECK2 count =", collection.count())
    model, q_emb = process_user_query(q)  # 섹션3 → embedding shape (384,)
    print("CHECK3 dim =", len(q_emb))
    hits = search_vector_database(
        collection, q_emb, top_k=3
    )  # 섹션4 → top-3 정책 + similarity
    print(
        "CHECK4 top1 =", hits[0]["metadata"]["title"], round(hits[0]["similarity"], 3)
    )
    prompt = augment_prompt_with_context(q, hits)  # 섹션5 → 프롬프트에 정책 본문 박힘
    print("CHECK5 prompt_len =", len(prompt))
    answer = generate_response(prompt)  # 섹션6 → 진짜 LLM 응답
    print("\n🎉 ANSWER:\n" + answer)
