-- Remove production case data for tombstoned indexnumberids (oca_metadata.deletedate).
-- Child rows cascade from oca_index; oca_metadata rows are preserved.

DELETE FROM oca_index
WHERE indexnumberid IN (
    SELECT m.indexnumberid
    FROM oca_metadata m
    WHERE m.deletedate IS NOT NULL
);
