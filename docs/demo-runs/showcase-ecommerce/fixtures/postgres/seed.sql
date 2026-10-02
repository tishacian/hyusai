-- Luma Maison, fixture v1; never loads measured time or ROI.
-- Run with an operator account on the intended demo DB, not the agent reader.
-- Inserts preserve existing rows; no DROP, DELETE or state reset.
BEGIN;
CREATE SCHEMA IF NOT EXISTS showcase_ecommerce;

CREATE TABLE IF NOT EXISTS showcase_ecommerce.customers (
  customer_id TEXT PRIMARY KEY, display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS showcase_ecommerce.orders (
  order_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES showcase_ecommerce.customers(customer_id),
  ordered_at TIMESTAMPTZ NOT NULL, paid_amount NUMERIC(12,2) NOT NULL CHECK (paid_amount >= 0),
  currency TEXT NOT NULL CHECK (currency = 'EUR'), shipping_postcode TEXT NOT NULL,
  payment_status TEXT NOT NULL CHECK (payment_status IN ('paid','unpaid'))
);
CREATE TABLE IF NOT EXISTS showcase_ecommerce.order_items (
  item_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES showcase_ecommerce.orders(order_id),
  product_name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0)
);
CREATE TABLE IF NOT EXISTS showcase_ecommerce.shipments (
  shipment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES showcase_ecommerce.orders(order_id),
  tracking_id TEXT NOT NULL UNIQUE, carrier TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('delivered','lost','in_transit')), status_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS showcase_ecommerce.refunds (
  refund_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES showcase_ecommerce.orders(order_id),
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0), currency TEXT NOT NULL CHECK (currency = 'EUR'),
  status TEXT NOT NULL CHECK (status IN ('prepared','approved','executed','failed')),
  executed_at TIMESTAMPTZ,
  CHECK ((status = 'executed' AND executed_at IS NOT NULL) OR (status <> 'executed' AND executed_at IS NULL))
);
CREATE TABLE IF NOT EXISTS showcase_ecommerce.claims (
  claim_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES showcase_ecommerce.orders(order_id),
  reason TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('to_investigate','waiting_information','awaiting_decision','resolved')),
  opened_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS showcase_ecommerce.document_refs (
  document_key TEXT PRIMARY KEY, source_filename TEXT NOT NULL, document_type TEXT NOT NULL,
  version TEXT NOT NULL, effective_from DATE NOT NULL, is_current BOOLEAN NOT NULL,
  order_id TEXT REFERENCES showcase_ecommerce.orders(order_id),
  sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  knowledge_source_id TEXT
);
COMMENT ON SCHEMA showcase_ecommerce IS 'Synthetic Luma Maison demo; no measured business gains';
COMMENT ON COLUMN showcase_ecommerce.document_refs.knowledge_source_id IS
  'NULL until a source is actually ingested in the matching Agentium workspace';

INSERT INTO showcase_ecommerce.customers (customer_id, display_name) VALUES
  ('C-014', 'Client fictif 014'),
  ('C-015', 'Client fictif 015'),
  ('C-016', 'Client fictif 016')
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO showcase_ecommerce.orders (order_id, customer_id, ordered_at, paid_amount, currency, shipping_postcode, payment_status) VALUES
  ('LM-1042', 'C-014', '2026-09-20T10:00:00Z', '420.00', 'EUR', '75011', 'paid'),
  ('LM-1043', 'C-015', '2026-09-21T10:00:00Z', '49.90', 'EUR', '69003', 'paid'),
  ('LM-1044', 'C-016', '2026-09-02T10:00:00Z', '89.00', 'EUR', '33000', 'paid')
ON CONFLICT (order_id) DO NOTHING;

INSERT INTO showcase_ecommerce.order_items (item_id, order_id, product_name, quantity, unit_price) VALUES
  ('LI-1042', 'LM-1042', 'Lampe Aube', 1, '420.00'),
  ('LI-1043', 'LM-1043', 'Vase Horizon', 1, '49.90'),
  ('LI-1044', 'LM-1044', 'Plaid Nuage', 1, '89.00')
ON CONFLICT (item_id) DO NOTHING;

INSERT INTO showcase_ecommerce.shipments (shipment_id, order_id, tracking_id, carrier, status, status_at) VALUES
  ('SH-1042', 'LM-1042', 'CA-1042', 'ColisAzur', 'delivered', '2026-09-24T14:00:00Z'),
  ('SH-1043', 'LM-1043', 'CA-1043', 'ColisAzur', 'lost', '2026-09-28T14:00:00Z'),
  ('SH-1044', 'LM-1044', 'CA-1044', 'ColisAzur', 'delivered', '2026-09-04T14:00:00Z')
ON CONFLICT (shipment_id) DO NOTHING;

INSERT INTO showcase_ecommerce.refunds (refund_id, order_id, amount, currency, status, executed_at) VALUES
  ('RF-1044', 'LM-1044', '89.00', 'EUR', 'executed', '2026-09-06T10:00:00Z')
ON CONFLICT (refund_id) DO NOTHING;

INSERT INTO showcase_ecommerce.claims (claim_id, order_id, reason, state, opened_at) VALUES
  ('RC-1042', 'LM-1042', 'delivery_disputed', 'to_investigate', '2026-09-25T10:00:00Z'),
  ('RC-1043', 'LM-1043', 'parcel_lost', 'to_investigate', '2026-09-29T10:00:00Z'),
  ('RC-1044', 'LM-1044', 'refund_requested', 'to_investigate', '2026-09-29T11:00:00Z')
ON CONFLICT (claim_id) DO NOTHING;

INSERT INTO showcase_ecommerce.document_refs (document_key, source_filename, document_type, version, effective_from, is_current, order_id, sha256, knowledge_source_id) VALUES
  ('refund-policy-v2', 'politique-remboursement-v2.pdf', 'policy', '2', '2026-09-01', TRUE, NULL, '240adbc2cd772111c015b5b3530b4dc8c3c9c98cf16d14c4aef6229420eb66a5', NULL),
  ('investigation-guide-v1', 'procedure-enquete-livraison-v1.docx', 'procedure', '1', '2026-09-01', TRUE, NULL, 'e352f66e19676abf8c0b9659412d7fe8de4799b100607bc8ddf533127aca2369', NULL),
  ('carrier-contract-v1', 'contrat-transporteur-v1.pdf', 'contract', '1', '2026-09-01', TRUE, NULL, '293f6a9e88c31113cdbf253b93626147eb40305991c6db0835ed47b2d871cf20', NULL),
  ('decision-guide-v1', 'guide-validation-sav-v1.pdf', 'decision_guide', '1', '2026-09-01', TRUE, NULL, '642cf61d82934e2160d7c7fc9729a9cac6f6a8ee951b9fca3a322287937cbf02', NULL),
  ('refund-policy-v1-archived', 'politique-remboursement-v1-archive.md', 'policy', '1', '2026-01-01', FALSE, NULL, '258e2430c4dcc8132372029304d24cd223b372ec84e85a2790d04abcde6dc80c', NULL),
  ('claim-lm1042', 'reclamation-lm1042.pdf', 'customer_claim', '1', '2026-09-25', TRUE, 'LM-1042', '93bf77e89542d7f412d7e040886cfd6908fdff10d6cae6513a8573c0328dd623', NULL),
  ('delivery-lm1042', 'bordereau-livraison-lm1042.pdf', 'delivery_receipt', '1', '2026-09-24', TRUE, 'LM-1042', '6339d30a66dea9e283f78c6a169d060da3123fca734634f71f9773191af24832', NULL),
  ('claim-lm1043', 'reclamation-lm1043.pdf', 'customer_claim', '1', '2026-09-29', TRUE, 'LM-1043', '1fecc56c020544d4341552d816528c90106aa34fb14a8f4f1f497de2030ec6b8', NULL),
  ('loss-lm1043', 'confirmation-perte-lm1043.pdf', 'carrier_loss_confirmation', '1', '2026-09-28', TRUE, 'LM-1043', '7810b679e1376999e4b4f81ed92970237708665623cf5a11ccc70c6f9310b354', NULL),
  ('claim-lm1044', 'reclamation-lm1044.pdf', 'customer_claim', '1', '2026-09-29', TRUE, 'LM-1044', 'c7d21c93045852ffd0694a0fc6f05f7aa69ebc10f8ce331977ef3dce1f8eaab6', NULL),
  ('refund-receipt-lm1044', 'recu-remboursement-lm1044.pdf', 'refund_receipt', '1', '2026-09-06', TRUE, 'LM-1044', '46409b2411b6c479b747b5befbddca83e3bf3dac572cd3c4b2d86ce77a95527e', NULL)
ON CONFLICT (document_key) DO NOTHING;

COMMIT;
