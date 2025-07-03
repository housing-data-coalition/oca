-- run occasionally
REINDEX SCHEMA public;

VACUUM ANALYZE oca_index;
VACUUM ANALYZE oca_causes;
VACUUM ANALYZE oca_addresses;
VACUUM ANALYZE oca_parties;
VACUUM ANALYZE oca_events;
VACUUM ANALYZE oca_appearances;
VACUUM ANALYZE oca_appearance_outcomes;
VACUUM ANALYZE oca_motions;
VACUUM ANALYZE oca_decisions;
VACUUM ANALYZE oca_judgments;
VACUUM ANALYZE oca_warrants;
VACUUM ANALYZE oca_metadata;