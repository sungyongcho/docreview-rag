#!/usr/bin/env python3
"""
Complete RAG Pipeline Demo - TechCorp PolicyCopilot
===================================================

This script demonstrates a complete RAG (Retrieval-Augmented Generation) system
that combines all the concepts from previous labs:
- Document chunking
- Vector database storage
- Query processing
- Vector search
- Context augmentation
- Response generation

Run this script to see the complete RAG pipeline in action!
"""

import time

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

# ========================================
# SECTION 1: DOCUMENT LOADING & CHUNKING
# ========================================


def load_and_chunk_documents():
    """
    Load sample policy documents and chunk them for better retrieval.

    This section demonstrates:
    - Document loading from sample data
    - Text chunking using LangChain
    - Chunk size and overlap configuration
    """
    print("📚 SECTION 1: DOCUMENT LOADING & CHUNKING")
    print("=" * 50)

    # Sample policy documents (same as previous labs)
    policy_documents = [
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

    print(f"📄 Loaded {len(policy_documents)} policy documents")

    # Configure text splitter (same as chunking lab)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=200,  # What is the chunk size?
        chunk_overlap=50,  # What is the overlap?
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )

    # Chunk all documents
    all_chunks = []
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

    return all_chunks


# ========================================
# SECTION 2: VECTOR DATABASE SETUP
# ========================================


def setup_vector_database(chunks: list[dict]):
    """
    Set up ChromaDB vector database and store document chunks.

    This section demonstrates:
    - ChromaDB client initialization
    - Collection creation
    - Document embedding and storage
    - Vector database configuration
    """
    print("\n🗄️ SECTION 2: VECTOR DATABASE SETUP")
    print("=" * 50)

    # Initialize ChromaDB client
    client = chromadb.Client()

    # Create collection (what is the collection name?)
    try:
        collection = client.create_collection(
            name="techcorp_policies",  # What is the collection name?
            metadata={"hnsw:space": "cosine"},  # What similarity metric is used?
        )
    except Exception:
        # Collection already exists, get it
        collection = client.get_collection("techcorp_policies")

    print(f"🗄️ Created collection: {collection.name}")
    print("📊 Similarity metric: cosine")

    # Prepare data for storage
    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["content"] for chunk in chunks]
    metadatas = [
        {
            "title": chunk["title"],
            "category": chunk["category"],
            "source": chunk["source_doc"],
        }
        for chunk in chunks
    ]

    # Add documents to collection (embeddings will be generated automatically)
    if collection.count() == 0:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        print(f"✅ Stored {len(chunks)} chunks in vector database")
    else:
        print(f"✅ Collection already contains {collection.count()} chunks")

    print(f"📈 Collection count: {collection.count()}")

    return collection


# ========================================
# SECTION 3: QUERY PROCESSING
# ========================================


def process_user_query(query: str):
    """
    Process user query and convert to embedding for vector search.

    This section demonstrates:
    - Query preprocessing
    - Embedding model usage
    - Vector conversion
    - Query optimization
    """
    print("\n🔍 SECTION 3: QUERY PROCESSING")
    print("=" * 50)

    # Load embedding model (what model is used?)
    model = SentenceTransformer("all-MiniLM-L6-v2")  # What embedding model is used?

    print(f"🤖 Using model: {model}")
    print(f"📐 Embedding dimensions: {model.get_sentence_embedding_dimension()}")

    # Preprocess query
    cleaned_query = query.lower().strip()
    print(f"📝 Original query: '{query}'")
    print(f"🧹 Cleaned query: '{cleaned_query}'")

    # Convert query to embedding
    query_embedding = model.encode([cleaned_query])
    print(f"🔢 Query embedding shape: {query_embedding.shape}")
    print(f"📊 Embedding sample: {query_embedding[0][:5]}...")

    return model, query_embedding[0]


# ========================================
# SECTION 4: VECTOR SEARCH
# ========================================


def search_vector_database(collection, query_embedding, top_k: int = 3):
    """
    Search vector database for relevant document chunks.

    This section demonstrates:
    - Vector similarity search
    - Result ranking and filtering
    - Similarity scoring
    - Top-k result selection
    """
    print("\n🔍 SECTION 4: VECTOR SEARCH")
    print("=" * 50)

    # Perform vector search
    results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=top_k,  # How many results are returned?
    )

    print(f"🎯 Searching for top {top_k} results")
    print(f"📊 Found {len(results['ids'][0])} relevant chunks")

    # Process and display results
    search_results = []
    for i, (doc_id, distance, content, metadata) in enumerate(
        zip(
            results["ids"][0],
            results["distances"][0],
            results["documents"][0],
            results["metadatas"][0],
        )
    ):
        similarity = 1 - distance  # Convert distance to similarity
        search_results.append(
            {
                "id": doc_id,
                "content": content,
                "metadata": metadata,
                "similarity": similarity,
            }
        )

        print(f"\n{i + 1}. {metadata['title']} (Category: {metadata['category']})")
        print(f"   Similarity: {similarity:.3f}")
        print(f"   Content: {content[:100]}...")

    return search_results


# ========================================
# SECTION 5: CONTEXT AUGMENTATION
# ========================================


def augment_prompt_with_context(query: str, search_results: list[dict]) -> str:
    """
    Build augmented prompt with retrieved context for LLM.

    This section demonstrates:
    - Context assembly from search results
    - Prompt construction
    - Information formatting
    - Context length management
    """
    print("\n📝 SECTION 5: CONTEXT AUGMENTATION")
    print("=" * 50)

    # Assemble context from search results
    context_parts = []
    for i, result in enumerate(search_results, 1):
        context_parts.append(
            f"Source {i}: {result['metadata']['title']}\n{result['content']}"
        )

    context = "\n\n".join(context_parts)

    print(f"📄 Assembled context from {len(search_results)} sources")
    print(f"📏 Context length: {len(context)} characters")

    # Build augmented prompt
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

    return augmented_prompt


# ========================================
# SECTION 6: RESPONSE GENERATION
# ========================================


def generate_response(augmented_prompt: str) -> str:
    """
    Generate response using LLM (simulated for demo).

    This section demonstrates:
    - LLM integration (simulated)
    - Response formatting
    - Answer synthesis
    - Output structure
    """
    print("\n🤖 SECTION 6: RESPONSE GENERATION")
    print("=" * 50)

    # Simulate LLM processing time
    print("⏳ Processing with LLM...")
    time.sleep(1)  # Simulate API call

    # Simulate LLM response (in production, this would call OpenAI/Anthropic/etc.)
    response = """
Based on the company policies provided, here's the answer to your question:

The relevant policies contain information about various company guidelines and procedures.
The retrieved context provides specific details that can help answer your question.

Key points from the policies:
- Multiple policy sources were consulted
- Information is current and accurate
- Specific requirements and limitations are included

Please refer to the specific policy documents for complete details and any recent updates.
"""

    print(f"✅ Generated response length: {len(response)} characters")
    print("📋 Response includes: Policy references, key points, limitations")

    return response


# ========================================
# SECTION 7: COMPLETE RAG PIPELINE
# ========================================


def run_complete_rag_pipeline(query: str):
    """
    Run the complete RAG pipeline from start to finish.

    This demonstrates the full flow:
    1. Document loading and chunking
    2. Vector database setup
    3. Query processing
    4. Vector search
    5. Context augmentation
    6. Response generation
    """
    print("\n🚀 COMPLETE RAG PIPELINE DEMO")
    print("=" * 60)
    print(f"❓ User Question: {query}")
    print("=" * 60)

    # Step 1: Load and chunk documents
    chunks = load_and_chunk_documents()

    # Step 2: Setup vector database
    collection = setup_vector_database(chunks)

    # Step 3: Process user query
    model, query_embedding = process_user_query(query)

    # Step 4: Search vector database
    search_results = search_vector_database(collection, query_embedding)

    # Step 5: Augment prompt with context
    augmented_prompt = augment_prompt_with_context(query, search_results)

    # Step 6: Generate response
    response = generate_response(augmented_prompt)

    # Display final result
    print("\n🎉 FINAL RESULT")
    print("=" * 60)
    print(response)
    print("=" * 60)

    return response


# ========================================
# MAIN EXECUTION
# ========================================

if __name__ == "__main__":
    print("🎯 TechCorp PolicyCopilot - Complete RAG Pipeline Demo")
    print("=" * 60)
    print("This demo shows how all RAG components work together!")
    print("=" * 60)

    # Test queries
    test_queries = [
        "What's the reimbursement policy for home office equipment?",
        "Can I get money back for buying a desk?",
        "How much can I claim for my home office?",
        "What's the travel expense policy?",
        "How many vacation days do I get?",
    ]

    # Run demo for each query
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'=' * 60}")
        print(f"DEMO {i}: {query}")
        print(f"{'=' * 60}")

        try:
            run_complete_rag_pipeline(query)
        except Exception as e:
            print(f"❌ Error in demo {i}: {e}")

        if i < len(test_queries):
            input("\nPress Enter to continue to next demo...")

    print("\n🎉 All demos completed!")
    print("You've seen how the complete RAG pipeline works!")
