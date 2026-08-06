-- Indexes supporting deterministic, scoped promotion deletes (idempotent reruns).
CREATE INDEX IF NOT EXISTS oca_addresses_promotion_natural_key_idx
    ON oca_addresses (indexnumberid, street1, street2, city, state, postalcode);

CREATE INDEX IF NOT EXISTS oca_index_staging_indexnumberid_idx
    ON oca_index_staging (indexnumberid);
