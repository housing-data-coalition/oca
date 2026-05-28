"""Synthetic OCA XML zip fixtures for repeatable parse-pipeline benchmarks."""

from __future__ import annotations

import io
import zipfile
from typing import Literal

from .etl_constants import DATA_FILENAME

NS = 'http://www.example.org/LandlordTenantExtractSchema'
NS_MAP = {'lt': NS}


def _tag(local: str) -> str:
    return f'{{{NS}}}{local}'


def _el(parent, local: str, text: str | None = None):
    elem = parent.makeelement(_tag(local))
    if text is not None:
        elem.text = text
    parent.append(elem)
    return elem


def build_case_xml(
    index_id: str,
    *,
    with_delete: bool = False,
    num_parties: int = 2,
    num_events: int = 2,
    num_appearances: int = 1,
    num_judgments: int = 1,
    num_warrants_per_judgment: int = 1,
) -> str:
    """Return one Index element as an XML string."""
    from lxml import etree

    case = etree.Element(_tag('Index'))
    _el(case, 'IndexNumberId', index_id)
    _el(case, 'Court', 'Housing Part')
    _el(case, 'FiledDate', '2024-01-15')
    _el(case, 'PropertyType', 'Residential')
    _el(case, 'Classification', 'Nonpayment')
    _el(case, 'Status', 'Active')
    _el(case, 'FirstPaper', 'Petition by Attorney')

    causes = etree.SubElement(case, _tag('PrimaryClaimCauseOfActions'))
    cause = etree.SubElement(causes, _tag('PrimaryClaimCauseOfAction'))
    _el(cause, 'CauseOfActionType', 'Rent Arrears')
    _el(cause, 'Amount', '5000.00')

    addresses = etree.SubElement(case, _tag('PropertyAddresses'))
    address = etree.SubElement(addresses, _tag('PropertyAddress'))
    _el(address, 'Street1', '123 Main St')
    _el(address, 'City', 'New York')
    _el(address, 'State', 'NY')
    _el(address, 'PostalCode', '10001')

    parties_parent = etree.SubElement(case, _tag('Parties'))
    for i in range(num_parties):
        party = etree.SubElement(parties_parent, _tag('Party'))
        _el(party, 'Role', 'Petitioner' if i == 0 else 'Respondent')
        _el(party, 'PartyType', 'Individual')

    events_parent = etree.SubElement(case, _tag('Events'))
    for i in range(num_events):
        event = etree.SubElement(events_parent, _tag('Event'))
        _el(event, 'EventName', f'Event {i}')
        _el(event, 'FiledDate', '2024-02-01')

    appearances_parent = etree.SubElement(case, _tag('Appearances'))
    for i in range(num_appearances):
        appearance = etree.SubElement(appearances_parent, _tag('Appearance'))
        _el(appearance, 'AppearanceDateTime', '2024-02-15T10:00:00')
        _el(appearance, 'AppearancePurpose', 'Conference')
        outcomes = etree.SubElement(appearance, _tag('AppearanceOutcomes'))
        outcome = etree.SubElement(outcomes, _tag('AppearanceOutcome'))
        _el(outcome, 'AppearanceOutcomeType', 'Adjourned')

    motions_parent = etree.SubElement(case, _tag('Motions'))
    motion = etree.SubElement(motions_parent, _tag('Motion'))
    _el(motion, 'Sequence', '1')
    _el(motion, 'MotionType', 'Default')

    decisions_parent = etree.SubElement(case, _tag('Decisions'))
    decision = etree.SubElement(decisions_parent, _tag('Decision'))
    _el(decision, 'Sequence', '1')
    _el(decision, 'ResultOf', 'Motion')

    judgments_parent = etree.SubElement(case, _tag('Judgments'))
    for j in range(num_judgments):
        judgment = etree.SubElement(judgments_parent, _tag('Judgment'))
        seq = str(j + 1)
        _el(judgment, 'Sequence', seq)
        _el(judgment, 'JudgmentType', 'Money')
        _el(judgment, 'FiledDate', '2024-03-01')
        warrants_parent = etree.SubElement(judgment, _tag('Warrants'))
        for w in range(num_warrants_per_judgment):
            warrant = etree.SubElement(warrants_parent, _tag('Warrant'))
            _el(warrant, 'Sequence', str(w + 1))
            _el(warrant, 'CreatedReason', 'Nonpayment')

    if with_delete:
        etree.SubElement(case, _tag('Delete'))

    return etree.tostring(case, encoding='unicode')


def build_extract_xml(
    case_count: int,
    *,
    extract_date: str = '2024-03-08',
    delete_every: int | None = None,
    child_profile: Literal['weekly', 'heavy'] = 'weekly',
) -> bytes:
    """Build a full LandlordTenantExtract XML document."""
    if child_profile == 'weekly':
        parties, events, appearances = 2, 2, 1
        judgments, warrants = 1, 1
    else:
        parties, events, appearances = 5, 5, 3
        judgments, warrants = 2, 2

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<LandlordTenantExtract xmlns="{NS}">',
        f'<RunDate>{extract_date}</RunDate>',
    ]
    for i in range(case_count):
        index_id = f'LT-BENCH-{i:06d}'
        with_delete = delete_every is not None and delete_every > 0 and i % delete_every == 0
        parts.append(
            build_case_xml(
                index_id,
                with_delete=with_delete,
                num_parties=parties,
                num_events=events,
                num_appearances=appearances,
                num_judgments=judgments,
                num_warrants_per_judgment=warrants,
            )
        )
    parts.append('</LandlordTenantExtract>')
    return ''.join(parts).encode('utf-8')


def write_benchmark_zip(
    zip_path: str,
    case_count: int,
    *,
    zip_basename: str | None = None,
    child_profile: Literal['weekly', 'heavy'] = 'weekly',
) -> str:
    """Write a zip file containing LandlordTenantExtract.xml; return zip path."""
    xml_bytes = build_extract_xml(case_count, child_profile=child_profile)
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(DATA_FILENAME, xml_bytes)
    return zip_path


SAMPLE_PROFILES = {
    'weekly': {
        'case_count': 250,
        'child_profile': 'weekly',
        'zip_name': 'LandlordTenant.Incr.2024-03-08.zip',
        'description': 'Representative weekly incremental (~250 cases, moderate children)',
    },
    'heavy': {
        'case_count': 2500,
        'child_profile': 'heavy',
        'zip_name': 'LandlordTenant.Initial.FiledIn2024.2024-03-01.zip',
        'description': 'Heavier backfill-style (~2500 cases, richer child collections)',
    },
}


def materialize_benchmark_samples(output_dir: str, profiles: list[str] | None = None) -> dict[str, str]:
    """Create fixed-input zip files under output_dir; return profile -> path."""
    import os

    os.makedirs(output_dir, exist_ok=True)
    selected = profiles or list(SAMPLE_PROFILES.keys())
    paths = {}
    for name in selected:
        spec = SAMPLE_PROFILES[name]
        zip_path = os.path.join(output_dir, spec['zip_name'])
        write_benchmark_zip(
            zip_path,
            spec['case_count'],
            child_profile=spec['child_profile'],
        )
        paths[name] = zip_path
    return paths
