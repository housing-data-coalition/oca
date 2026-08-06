import fnmatch

from .etl_constants import DATA_ZIPFILE_PAT, S3_PRIVATE_FOLDER
from .etl_helpers import s3_key


def list_new_data_files(sftp, s3, s3_prefix=''):
    """ 
    Get a list of filenames for all the data files available in the SFTP
    that are not already in the private S3 folder. These are the new ones 
    that still need to be processed. They are returned in the proper order 
    in which they need to be processed.

    :param sftp: SFTP object
    :param s3: S3 object
    """

    sftp_zip_files = sftp.list_files(DATA_ZIPFILE_PAT)
    s3_zip_files = s3.list_files(DATA_ZIPFILE_PAT, s3_key(S3_PRIVATE_FOLDER, s3_prefix))
    new_sftp_zip_files = list(set(sftp_zip_files) - set(s3_zip_files))

    # It's important that everything is processed in order because files 
    # can contain modify/delete cases included in past files
    init_files = [f for f in new_sftp_zip_files if 'Initial' in f]
    incr_files = [f for f in new_sftp_zip_files if 'Incr' in f]

    files = []
    files += sorted(init_files) if init_files else []
    files += sorted(incr_files) if incr_files else []

    return files


def list_reprocess_data_files(s3, reprocess_glob, s3_prefix=''):
    if not reprocess_glob:
        return []
    s3_zip_files = s3.list_files(DATA_ZIPFILE_PAT, s3_key(S3_PRIVATE_FOLDER, s3_prefix))
    return sorted([f for f in s3_zip_files if fnmatch.fnmatch(f, reprocess_glob)])


def select_data_files_to_process(new_files, reprocess_files, force_reprocess=False):
    def ordered(files):
        init_files = sorted([f for f in files if 'Initial' in f])
        incr_files = sorted([f for f in files if 'Incr' in f])
        return init_files + incr_files

    if not reprocess_files:
        return ordered(new_files)

    if not force_reprocess:
        # Keep backward-compatible default behavior unless force mode is explicitly set.
        return ordered(new_files)

    merged = set(new_files) | set(reprocess_files)
    return ordered(merged)
