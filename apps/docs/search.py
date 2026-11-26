"""One snippet query: the `document_search` tool and `/documents/` read the same rows (§10)."""

from django.db import connection

SNIPPET_OPTIONS = "StartSel=«,StopSel=»,MaxFragments=2,MinWords=6,MaxWords=20"

SQL = """
SELECT d.id,
       d.filename,
       d.case_id,
       c.reference AS case_reference,
       c.title AS case_title,
       d.no_text_layer,
       ts_headline('spanish', d.extracted_text, q, %(options)s) AS snippet,
       ts_rank(d.search_vector, q) AS rank
FROM docs_document d
JOIN core_case c ON c.id = d.case_id
JOIN core_client cl ON cl.id = c.client_id
CROSS JOIN websearch_to_tsquery('spanish', %(query)s) AS q
WHERE d.is_active AND d.search_vector @@ q
  {case_filter}
ORDER BY (ts_rank(d.search_vector, q)
          + greatest(similarity(c.reference, %(query)s),
                     similarity(c.title, %(query)s),
                     similarity(cl.name, %(query)s))) DESC,
         d.created_at DESC
LIMIT %(limit)s
"""


def search(query, case_id=None, limit=20):
    """Full-text hits with a snippet, boosted by a trigram match on case or client."""
    query = (query or "").strip()
    if not query:
        return []
    sql = SQL.format(case_filter="AND d.case_id = %(case_id)s" if case_id else "")
    params = {"query": query, "options": SNIPPET_OPTIONS, "limit": limit}
    if case_id:
        params["case_id"] = case_id
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [column.name for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
