ALTER TABLE inventory_actions
ADD COLUMN request_nonce TEXT;

CREATE UNIQUE INDEX inventory_actions_unique_request_nonce
ON inventory_actions(request_nonce)
WHERE request_nonce IS NOT NULL;

ALTER TABLE inventory_workflow_transactions
ADD COLUMN print_job_name TEXT;

ALTER TABLE inventory_workflow_transactions
ADD COLUMN approximate_layer INTEGER CHECK(approximate_layer IS NULL OR approximate_layer>=0);

ALTER TABLE inventory_workflow_transactions
ADD COLUMN printer TEXT;

ALTER TABLE inventory_workflow_transactions
ADD COLUMN plate TEXT;

ALTER TABLE inventory_workflow_transactions
ADD COLUMN operational_note TEXT;

