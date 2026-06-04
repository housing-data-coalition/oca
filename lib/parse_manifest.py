"""Manifest details for per-zip parse results (no heavy ETL imports)."""


class ParseFailFastError(RuntimeError):
    """Raised when PARSE_FAIL_FAST is set and any zip has case-level parse failures."""


def cases_failed_from_details(details):
    if not details:
        return 0
    return int(details.get('cases_failed') or 0)


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


def upsert_promoted_etl_file(manifest, file_name, source, parse_details):
    """Mark file completed after promote only when parse had zero failures."""
    cases_failed = cases_failed_from_details(parse_details)
    if cases_failed > 0:
        details = dict(parse_details)
        details['parse_complete'] = False
        manifest.upsert_file(
            file_name,
            source=source,
            status='parsed',
            stage='parse',
            details=details,
        )
        return False
    manifest.upsert_file(
        file_name,
        source=source,
        status='completed',
        stage='promote',
        details=parse_details,
    )
    return True


def file_names_needing_reprocess(file_details_by_name):
    return sorted(
        name
        for name, details in file_details_by_name.items()
        if cases_failed_from_details(details) > 0
    )


def finalize_parse_xml_step(manifest, total_cases_failed, files_with_failures, parse_fail_fast=False):
    """Complete or fail the parse_xml manifest step; optionally abort before export/promote."""
    step_details = build_parse_xml_step_details(total_cases_failed, files_with_failures)
    if parse_fail_fast and total_cases_failed > 0:
        for file_name, details in manifest.file_details_by_name.items():
            if cases_failed_from_details(details) > 0:
                manifest.upsert_file(
                    file_name,
                    source='local',
                    status='failed',
                    stage='parse',
                    details=details,
                    error=ParseFailFastError(
                        f"{details.get('cases_failed', 0)} case(s) failed in {file_name}"
                    ),
                )
        manifest.upsert_step(
            'parse_xml',
            'failed',
            details=step_details,
            error=ParseFailFastError(
                f"PARSE_FAIL_FAST: {total_cases_failed} case failure(s) across "
                f"{files_with_failures} file(s)"
            ),
        )
        raise ParseFailFastError(
            f"PARSE_FAIL_FAST: aborting before export/promote ({total_cases_failed} case failure(s))"
        )
    manifest.upsert_step('parse_xml', 'completed', details=step_details)
