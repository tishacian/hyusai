-- Intended bind variables for a server-side psycopg2 reader, not psql macros.
-- These statements do not open a connection or execute a reimbursement.

-- claim_context: one dossier and its order. : claim_id is a business ID.
SELECT c.claim_id, c.reason, c.state, c.opened_at,
       o.order_id, o.ordered_at, o.paid_amount, o.currency, o.payment_status,
       o.shipping_postcode, u.customer_id, u.display_name
FROM showcase_ecommerce.claims AS c
JOIN showcase_ecommerce.orders AS o ON o.order_id = c.order_id
JOIN showcase_ecommerce.customers AS u ON u.customer_id = o.customer_id
WHERE c.claim_id = %(claim_id)s
LIMIT 1;

-- claim_items
SELECT i.item_id, i.product_name, i.quantity, i.unit_price
FROM showcase_ecommerce.order_items AS i
JOIN showcase_ecommerce.claims AS c ON c.order_id = i.order_id
WHERE c.claim_id = %(claim_id)s
ORDER BY i.item_id
LIMIT 50;

-- claim_shipments: shipping_postcode belongs to the order; the receipt is documentary.
SELECT s.shipment_id, s.tracking_id, s.carrier, s.status, s.status_at
FROM showcase_ecommerce.shipments AS s
JOIN showcase_ecommerce.claims AS c ON c.order_id = s.order_id
WHERE c.claim_id = %(claim_id)s
ORDER BY s.status_at DESC, s.shipment_id
LIMIT 50;

-- claim_refunds: absence is distinct from a failed lookup.
SELECT r.refund_id, r.amount, r.currency, r.status, r.executed_at
FROM showcase_ecommerce.refunds AS r
JOIN showcase_ecommerce.claims AS c ON c.order_id = r.order_id
WHERE c.claim_id = %(claim_id)s
ORDER BY r.executed_at DESC NULLS LAST, r.refund_id
LIMIT 50;

-- claim_documents: current references only; still require Document Center access control.
SELECT d.document_key, d.source_filename, d.document_type, d.version,
       d.effective_from, d.order_id, d.sha256, d.knowledge_source_id
FROM showcase_ecommerce.document_refs AS d
JOIN showcase_ecommerce.claims AS c
  ON (d.order_id = c.order_id OR d.order_id IS NULL)
WHERE c.claim_id = %(claim_id)s AND d.is_current
ORDER BY d.document_type, d.document_key
LIMIT 50;
