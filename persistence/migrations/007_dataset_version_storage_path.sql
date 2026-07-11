ALTER TABLE dataset_version ADD COLUMN IF NOT EXISTS storage_path TEXT;

UPDATE dataset_version v
SET storage_path = d.storage_path
FROM dataset d
WHERE d.dataset_id = v.dataset_id
  AND v.storage_path IS NULL;
