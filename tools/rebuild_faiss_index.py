#!/usr/bin/env python3
"""
Rebuild FAISS index from existing database content
"""

import asyncio
import sys
import json
from pathlib import Path
sys.path.append('.')

from document_interrogator import get_document_interrogator

async def rebuild_faiss_index():
    """Rebuild FAISS index from existing database content"""
    
    print("🔄 Rebuilding FAISS Index from Database")
    print("=" * 50)
    
    interrogator = get_document_interrogator()
    store = interrogator.store
    
    # Get all chunks from database
    cursor = store.metadata_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM chunks")
    total_chunks = cursor.fetchone()[0]
    
    print(f"📊 Found {total_chunks} chunks in database")
    print(f"📊 Current FAISS index size: {store.faiss_index.ntotal}")
    
    if store.faiss_index.ntotal > 0:
        print("⚠️ FAISS index already has vectors. Clearing...")
        # Clear existing index
        store.faiss_index.reset()
    
    print("\n🔄 Starting rebuild process...")
    
    # Get all chunks with their content
    cursor.execute("""
        SELECT chunk_id, content, document_path 
        FROM chunks 
        ORDER BY faiss_index
    """)
    
    chunks_to_reindex = cursor.fetchall()
    
    batch_size = 100  # Process in batches
    total_processed = 0
    
    for i in range(0, len(chunks_to_reindex), batch_size):
        batch = chunks_to_reindex[i:i + batch_size]
        
        # Extract content for embedding generation
        batch_content = [chunk[1] for chunk in batch]  # content is index 1
        
        print(f"📦 Processing batch {i//batch_size + 1}: {len(batch)} chunks")
        
        try:
            # Generate embeddings for this batch
            embeddings = await store._generate_embeddings(batch_content)
            
            if not embeddings or len(embeddings) != len(batch):
                print(f"   ❌ Failed to generate embeddings for batch")
                continue
            
            # Add to FAISS index
            import numpy as np
            embeddings_array = np.array(embeddings).astype('float32')
            
            # SI-043 — on an id-mapped index, keep each chunk's EXISTING id rather than
            # renumbering by position; ids are stable and legitimately non-contiguous.
            if hasattr(store.faiss_index, "id_map"):
                batch_ids, next_id = [], None
                for chunk_id, _content, _doc_path in batch:
                    row = cursor.execute("SELECT faiss_index FROM chunks WHERE chunk_id = ?",
                                         (chunk_id,)).fetchone()
                    if row and row[0] is not None:
                        batch_ids.append(int(row[0]))
                    else:
                        if next_id is None:
                            next_id = (cursor.execute(
                                "SELECT COALESCE(MAX(faiss_index), -1) FROM chunks"
                            ).fetchone()[0]) + 1
                        batch_ids.append(next_id)
                        cursor.execute("UPDATE chunks SET faiss_index = ? WHERE chunk_id = ?",
                                       (next_id, chunk_id))
                        next_id += 1
                store.faiss_index.add_with_ids(embeddings_array,
                                               np.array(batch_ids, dtype='int64'))
            else:
                start_idx = store.faiss_index.ntotal
                store.faiss_index.add(embeddings_array)
                for j, (chunk_id, content, doc_path) in enumerate(batch):
                    cursor.execute("""
                        UPDATE chunks 
                        SET faiss_index = ? 
                        WHERE chunk_id = ?
                    """, (start_idx + j, chunk_id))
            
            store.metadata_db.commit()
            total_processed += len(batch)
            
            print(f"   ✅ Added {len(batch)} vectors to FAISS index")
            print(f"   📊 Progress: {total_processed}/{total_chunks} chunks ({100*total_processed/total_chunks:.1f}%)")
            
        except Exception as e:
            print(f"   ❌ Error processing batch: {e}")
            import traceback
            traceback.print_exc()
    
    # Save the rebuilt index
    try:
        await store._save_index()
        print(f"\n✅ Rebuild complete!")
        print(f"📊 Final FAISS index size: {store.faiss_index.ntotal}")
        print(f"📊 Total chunks processed: {total_processed}")
        
    except Exception as e:
        print(f"\n❌ Error saving index: {e}")

if __name__ == "__main__":
    asyncio.run(rebuild_faiss_index())