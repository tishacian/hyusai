SELECT c.claim_id, lower(trim(c.reason)) AS claim_reason,
       cast(o.paid_amount AS DOUBLE) AS paid_amount,
       lower(trim(s.status)) AS shipment_status,
       cast(coalesce(r.already_refunded, 0) AS INTEGER) AS already_refunded,
       cast(coalesce(d.case_documents, 0) AS INTEGER) AS case_documents,
       cast(i.item_quantity AS INTEGER) AS item_quantity
FROM claims c JOIN orders o ON o.order_id = c.order_id
JOIN (SELECT order_id, sum(quantity) AS item_quantity FROM order_items GROUP BY order_id) i
  ON i.order_id = c.order_id
LEFT JOIN (SELECT order_id, status FROM shipments
  QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY status_at DESC, shipment_id) = 1) s
  ON s.order_id = c.order_id
LEFT JOIN (SELECT order_id, max(cast(status = 'executed' AS INTEGER)) AS already_refunded
  FROM refunds GROUP BY order_id) r ON r.order_id = c.order_id
LEFT JOIN (SELECT order_id, count(*) AS case_documents FROM document_refs
  WHERE is_current AND order_id IS NOT NULL GROUP BY order_id) d ON d.order_id = c.order_id
ORDER BY c.claim_id
