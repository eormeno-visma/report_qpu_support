"""
Queries compartidas entre scripts.
"""

# Query maestro: define el listado y orden canónico de empresas activas
COMPANIES_QUERY = """
SELECT
    c.id        AS empresa_id,
    c.name      AS empresa_nombre,
    c.hubspot_id
FROM companies c
WHERE c.is_demo = 0
  AND c.active = 1
  AND c.name NOT LIKE '%QA%'
  AND c.name NOT LIKE '%Demo%'
  AND c.name NOT LIKE '%Ronald%'
  AND c.hubspot_id != ''
ORDER BY c.name;
"""

# Query Features IA — obtiene los switches IA por empresa desde companie_options
# Origen: superadmin.manduhr.com → /mandu/empresas/form/{id} → sección "IA"
#   • generateObjetiveWithAI  → switch "Objetivos con IA"
#   • feedbackWithAI          → switch "Feedback con IA"
IA_FEATURES_QUERY = """
SELECT
    c.id                          AS empresa_id,
    co.generateObjetiveWithAI     AS obj_ia,
    co.feedbackWithAI             AS feedback_ia
FROM companies c
LEFT JOIN companie_options co ON co.companie_id = c.id
WHERE c.is_demo = 0
  AND c.active = 1
  AND c.name NOT LIKE '%QA%'
  AND c.name NOT LIKE '%Demo%'
  AND c.name NOT LIKE '%Ronald%'
  AND c.hubspot_id != ''
ORDER BY c.name;
"""

