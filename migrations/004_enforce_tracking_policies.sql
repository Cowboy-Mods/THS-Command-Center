ALTER TABLE inventory_instances
ADD COLUMN tracking_policy_override INTEGER NOT NULL DEFAULT 0
CHECK(tracking_policy_override IN (0,1));

ALTER TABLE stock_lots
ADD COLUMN tracking_policy_override INTEGER NOT NULL DEFAULT 0
CHECK(tracking_policy_override IN (0,1));

CREATE TRIGGER inventory_instances_enforce_tracking_policy_insert
BEFORE INSERT ON inventory_instances
WHEN NEW.tracking_policy_override=0 AND (
  SELECT it.tracking_method
  FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id
  WHERE ci.id=NEW.catalog_item_id
) <> 'individual'
BEGIN
  SELECT RAISE(ABORT,'item type tracking policy does not allow individual instances');
END;

CREATE TRIGGER inventory_instances_enforce_tracking_policy_update
BEFORE UPDATE OF catalog_item_id,tracking_policy_override ON inventory_instances
WHEN NEW.tracking_policy_override=0 AND (
  SELECT it.tracking_method
  FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id
  WHERE ci.id=NEW.catalog_item_id
) <> 'individual'
BEGIN
  SELECT RAISE(ABORT,'item type tracking policy does not allow individual instances');
END;

CREATE TRIGGER stock_lots_enforce_tracking_policy_insert
BEFORE INSERT ON stock_lots
WHEN NEW.tracking_policy_override=0 AND (
  SELECT it.tracking_method
  FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id
  WHERE ci.id=NEW.catalog_item_id
) = 'individual'
BEGIN
  SELECT RAISE(ABORT,'item type tracking policy requires individual instances');
END;

CREATE TRIGGER stock_lots_enforce_tracking_policy_update
BEFORE UPDATE OF catalog_item_id,tracking_policy_override ON stock_lots
WHEN NEW.tracking_policy_override=0 AND (
  SELECT it.tracking_method
  FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id
  WHERE ci.id=NEW.catalog_item_id
) = 'individual'
BEGIN
  SELECT RAISE(ABORT,'item type tracking policy requires individual instances');
END;

CREATE TRIGGER item_types_enforce_tracking_policy_update
BEFORE UPDATE OF tracking_method ON item_types
WHEN (
  NEW.tracking_method='individual' AND EXISTS (
    SELECT 1 FROM catalog_items ci JOIN stock_lots sl ON sl.catalog_item_id=ci.id
    WHERE ci.item_type_id=NEW.id AND sl.tracking_policy_override=0
  )
) OR (
  NEW.tracking_method<>'individual' AND EXISTS (
    SELECT 1 FROM catalog_items ci JOIN inventory_instances ii ON ii.catalog_item_id=ci.id
    WHERE ci.item_type_id=NEW.id AND ii.tracking_policy_override=0
  )
)
BEGIN
  SELECT RAISE(ABORT,'existing inventory conflicts with requested tracking policy');
END;


