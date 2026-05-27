OCA_TABLES = [
    'oca_index',
    'oca_causes',
    'oca_addresses',
    'oca_parties',
    'oca_events',
    'oca_appearances',
    'oca_appearance_outcomes',
    'oca_motions',
    'oca_decisions',
    'oca_judgments',
    'oca_warrants',
    'oca_metadata'
]

DATA_ZIPFILE_PAT = r'LandlordTenant\.(Initial\.FiledIn\d{4}|Incr)\.\d{4}-\d{2}-\d{2}\.zip'

DATA_FILENAME = 'LandlordTenantExtract.xml'

S3_PRIVATE_FOLDER = 'private'

S3_PUBLIC_FOLDER = 'public'
