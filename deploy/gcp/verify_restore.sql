-- Read-only acceptance report consumed before the public app starts.
SELECT json_build_object(
    'documents', (SELECT json_agg(doc_id ORDER BY doc_id) FROM documents),
    'chunks', (SELECT count(*) FROM chunks),
    'embeddings', (SELECT count(*) FROM chunk_embeddings),
    'matching_embeddings', (
        SELECT count(*) FROM chunk_embeddings e JOIN chunks c ON c.id = e.chunk_id
        WHERE e.input_sha256 = c.index_text_sha256
          AND e.provider = 'openai' AND e.model = 'text-embedding-3-large'
          AND e.dimensions = 384 AND vector_dims(e.embedding) = 384
    ),
    'snapshots', (SELECT count(*) FROM evaluation_snapshots),
    'public_ready_snapshots', (
        SELECT count(*) FROM evaluation_snapshots WHERE public AND status = 'ready'
    ),
    'complete_snapshot_documents', (
        SELECT count(*) FROM (
            SELECT snapshot_id FROM snapshot_documents GROUP BY snapshot_id HAVING count(*) = 18
        ) complete
    ),
    'evaluation_paths', (SELECT json_agg(raw_artifact_path ORDER BY raw_artifact_path) FROM eval_results),
    'evaluations', (
        SELECT json_agg(json_build_object(
            'path', e.raw_artifact_path,
            'suite', e.suite,
            'config', e.config,
            'metrics', e.metrics,
            'snapshot_sources', (
                SELECT json_agg(json_build_object('doc_id', source.doc_id, 'source_sha256', source.source_sha256))
                FROM (
                    SELECT DISTINCT c.doc_id, c.source_sha256
                    FROM snapshot_chunks c
                    JOIN evaluation_snapshots s ON s.id = c.snapshot_id
                    WHERE s.eval_result_id = e.id
                ) source
            )
        ) ORDER BY e.raw_artifact_path)
        FROM eval_results e
    ),
    'linked_evaluations', (
        SELECT count(DISTINCT e.id) FROM eval_results e
        JOIN evaluation_snapshots s ON s.eval_result_id = e.id
    ),
    'runs', (SELECT count(*) FROM runs),
    'traces', (SELECT count(*) FROM traces),
    'operator_jobs', (SELECT count(*) FROM operator_jobs)
);
