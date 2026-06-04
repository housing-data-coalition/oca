"""Manifest details for per-zip parse results (no heavy ETL imports)."""


def build_parsed_file_details(extract_date, parse_result):
    return {
        'extract_date': extract_date,
        'cases_seen': parse_result.cases_seen,
        'cases_parsed_ok': parse_result.cases_parsed_ok,
        'cases_failed': parse_result.cases_failed,
        'error_samples': parse_result.error_samples,
    }


def upsert_parsed_etl_file(manifest, file_name, parse_result, extract_date):
    """Record per-zip parse counters on etl_files (status parsed)."""
    details = build_parsed_file_details(extract_date, parse_result)
    upsert_kwargs = {
        'file_name': file_name,
        'source': 'local',
        'status': 'parsed',
        'stage': 'parse',
        'details': details,
    }
    if parse_result.cases_failed > 0:
        upsert_kwargs['error'] = (
            f"{parse_result.cases_failed} of {parse_result.cases_seen} cases failed to parse"
        )
    manifest.upsert_file(**upsert_kwargs)
    return parse_result.cases_failed


def build_parse_xml_step_details(total_cases_failed, files_with_failures):
    return {
        'total_cases_failed': total_cases_failed,
        'files_with_failures': files_with_failures,
    }
