WITH normalized AS (
  SELECT
    trim(claim_id) AS claim_id,
    lower(trim(claim_reason)) AS claim_reason,
    try_cast(paid_amount AS DOUBLE) AS paid_amount,
    lower(trim(shipment_status)) AS shipment_status,
    try_cast(already_refunded AS INTEGER) AS already_refunded,
    try_cast(case_documents AS INTEGER) AS case_documents,
    try_cast(item_quantity AS INTEGER) AS item_quantity,
    try_cast(opened_at AS TIMESTAMPTZ) AS opened_at,
    try_cast(resolved_at AS TIMESTAMPTZ) AS resolved_at
  FROM input
), valid AS (
  SELECT *, row_number() OVER (PARTITION BY claim_id ORDER BY resolved_at DESC) AS source_rank
  FROM normalized
  WHERE resolved_at > opened_at
    AND claim_reason IN ('delivery_disputed', 'parcel_lost', 'refund_requested')
    AND shipment_status IN ('delivered', 'lost', 'in_transit')
    AND paid_amount >= 0 AND already_refunded IN (0, 1)
    AND case_documents >= 0 AND item_quantity > 0
)
SELECT claim_id, claim_reason, paid_amount, shipment_status, already_refunded,
       case_documents, item_quantity,
       cast(resolved_at > opened_at + INTERVAL '72 hours' AS INTEGER) AS resolution_over_72h
FROM valid WHERE source_rank = 1
ORDER BY claim_id
