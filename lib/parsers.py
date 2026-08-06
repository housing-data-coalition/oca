import logging
import queue
import threading
from dataclasses import dataclass, field

from lxml import etree

from .parse_write_buffer import attach_write_buffer, flush_write_buffer, staging_execute

logger = logging.getLogger(__name__)

PARSE_PROGRESS_INTERVAL = 1000
MAX_PARSE_ERROR_SAMPLES = 10
MAX_PARSE_ERROR_SAMPLE_LEN = 500


@dataclass
class ParseFileResult:
    """Per-zip parse health counters (thread-safe)."""

    cases_seen: int = 0
    cases_parsed_ok: int = 0
    cases_failed: int = 0
    error_samples: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record_seen(self) -> None:
        with self._lock:
            self.cases_seen += 1

    def record_ok(self) -> None:
        with self._lock:
            self.cases_parsed_ok += 1

    def record_failed(self, error: str) -> None:
        sample = _truncate_parse_error(str(error))
        with self._lock:
            self.cases_failed += 1
            if len(self.error_samples) < MAX_PARSE_ERROR_SAMPLES:
                self.error_samples.append(sample)


def _truncate_parse_error(message: str) -> str:
    if len(message) <= MAX_PARSE_ERROR_SAMPLE_LEN:
        return message
    return message[: MAX_PARSE_ERROR_SAMPLE_LEN - 3] + '...'


NAMESPACE = '{http://www.example.org/LandlordTenantExtractSchema}'

def oca_tag(tag):
    """ add the necessary namespace to an xml tag

    :param tag: an xml tag string
    :return: string for tag with namespace
    """
    return NAMESPACE + tag

INDEX_NUMBER_ID_TAG = oca_tag('IndexNumberId')
DELETE_TAG = oca_tag('Delete')


def _index_number_id_from_case(case) -> str | None:
    elem = case.find(INDEX_NUMBER_ID_TAG)
    return None if elem is None else elem.text


def is_case_to_delete(case):
    """ Determine if a case should be deleted from the database

    :param case: an lxml.etree element for a case index
    :return: boolean
    """
    return case.find(DELETE_TAG) is not None


def oca_extract(elem, tag):
    """ find the first occurance of an xml tag and extract the tag value

    :param elem: an lxml.etree element
    :param tag: an xml tag to find
    :return: string for node text
    """
    x = elem.find(oca_tag(tag))
    return None if x is None else x.text


def oca_extract_array1(elem, parent_tag, child_tag):
    """ find the first node for given parent tag then extract the text 
    for all children matching the child tag as a Python list

    :param elem: an lxml.etree element
    :param parent_tag: an xml tag for the parent node
    :param child_tag: an xml tag for the children nodes
    :return: Python list or None
    """
    parent_elem = elem.find(oca_tag(parent_tag))

    if parent_elem is not None:
        values = [i.text for i in parent_elem.findall(oca_tag(child_tag)) if i.text is not None]
        return values if values else None
    else:
        return None


def oca_extract_array2(elem, grandparent_tag, parent_tag, child_tag):
    """ find the first node for given grandparent tag then extract all 
    the parent nodes and for each parent node extract the text for its 
    child as a Python list

    :param elem: an lxml.etree element
    :param grandparent_tag: an xml tag for the grandparent node
    :param parent_tag: an xml tag for the parent nodes
    :param child_tag: an xml tag for the child node
    :return: Python list or None
    """
    grandparent_elem = elem.find(oca_tag(grandparent_tag))

    if grandparent_elem is not None:
        values = []
        for parent in grandparent_elem.findall(oca_tag(parent_tag)):
            child_elem = parent.find(oca_tag(child_tag))
            if child_elem is not None and child_elem.text is not None:
                values.append(child_elem.text)
        return values if values else None
    else:
        return None


def parse_index(case, db):
    """ for a case parse all the values for the oca_index 
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """
    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    row = {
        'indexnumberid' : IndexNumberId,
        'court' : oca_extract(case, 'Court'),
        'fileddate' : oca_extract(case, 'FiledDate'),
        'propertytype' : oca_extract(case, 'PropertyType'),
        'classification' : oca_extract(case, 'Classification'),
        'specialtydesignationtypes' : oca_extract_array1(case, 'SpecialtyDesignations', 'SpecialtyDesignationType'),
        'status' : oca_extract(case, 'Status'),
        'disposeddate' : oca_extract(case, 'DisposedDate'),
        'disposedreason' : oca_extract(case, 'DisposedReasonNoPersonallyIdentifyingInfo'),
        'firstpaper' : oca_extract(case, 'FirstPaper'),
        'primaryclaimtotal' : oca_extract(case, 'PrimaryClaimTotal'),
        'dateofjurydemand' : oca_extract(case, 'DateOfJuryDemand'),
    }

    columns = list(row.keys())
    values = tuple(row.get(col) for col in columns)
    placeholders = ', '.join(['?' for _ in columns])
    insert_sql = f"INSERT OR REPLACE INTO oca_index_staging ({', '.join(columns)}) VALUES ({placeholders})"
    staging_execute(db, insert_sql, values)


def parse_causes(case, db):
    """ for a case parse all the values for the oca_causes
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """
    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # Eelete existing records for this case to handle multiple causes
    staging_execute(db, "DELETE FROM oca_causes_staging WHERE indexnumberid = ?", (IndexNumberId,))

    causes = case.find(oca_tag('PrimaryClaimCauseOfActions'))

    if causes is None:
        return None

    for cause in causes.iter(oca_tag('PrimaryClaimCauseOfAction')):
        row = {
            'indexnumberid' : IndexNumberId,
            'causeofactiontype' : oca_extract(cause, 'CauseOfActionType'),
            'interestfromdate' : oca_extract(cause, 'InterestFromDate'),
            'amount' : oca_extract(cause, 'Amount'),
        }
        columns = list(row.keys())
        values = tuple(row.get(col) for col in columns)
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f"INSERT INTO oca_causes_staging ({', '.join(columns)}) VALUES ({placeholders})"
        staging_execute(db, insert_sql, values)


def parse_addresses(case, db):
    """ for a case parse all the values for the oca_addresses
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """
    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # First, delete existing records for this case to handle multiple addresses
    staging_execute(db, "DELETE FROM oca_addresses_staging WHERE indexnumberid = ?", (IndexNumberId,))

    addresses = case.find(oca_tag('PropertyAddresses'))

    if addresses is None:
        return None

    for address in addresses.iter(oca_tag('PropertyAddress')):
        row = {
            'indexnumberid' : IndexNumberId,
            'street1' : oca_extract(address, 'Street1'),
            'street2' : oca_extract(address, 'Street2'),
            'city' : oca_extract(address, 'City'),
            'state' : oca_extract(address, 'State'),
            'postalcode' : oca_extract(address, 'PostalCode'),
        }
        columns = list(row.keys())
        values = tuple(row.get(col) for col in columns)
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f"INSERT INTO oca_addresses_staging ({', '.join(columns)}) VALUES ({placeholders})"
        staging_execute(db, insert_sql, values)


def parse_parties(case, db):
    """ for a case parse all the values for the oca_parties
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """
    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # First, delete existing records for this case to handle multiple parties
    staging_execute(db, "DELETE FROM oca_parties_staging WHERE indexnumberid = ?", (IndexNumberId,))

    parties = case.find(oca_tag('Parties'))

    if parties is None:
        return None

    for party in parties.iter(oca_tag('Party')):
        row = {
            'indexnumberid' : IndexNumberId,
            'role' : oca_extract(party, 'Role'),
            'partytype' : oca_extract(party, 'PartyType'),
            'representationtype' : oca_extract(party, 'RepresentationType'),
            'undertenant' : oca_extract(party, 'Undertenant'),
        }
        columns = list(row.keys())
        values = tuple(row.get(col) for col in columns)
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f"INSERT INTO oca_parties_staging ({', '.join(columns)}) VALUES ({placeholders})"
        staging_execute(db, insert_sql, values)


def parse_events(case, db):
    """ for a case parse all the values for the oca_events
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """
    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # First, delete existing records for this case to handle multiple events
    staging_execute(db, "DELETE FROM oca_events_staging WHERE indexnumberid = ?", (IndexNumberId,))

    events = case.find(oca_tag('Events'))

    if events is None:
        return None

    for event in events.iter(oca_tag('Event')):
        row = {
            'indexnumberid' : IndexNumberId,
            'eventname' : oca_extract(event, 'EventName'),
            'fileddate' : oca_extract(event, 'FiledDate'),
            'feetype' : oca_extract(event, 'FeeType'),
            'filingpartiesroles' : oca_extract_array2(event, 'FilingParties', 'FilingParty', 'Role'),
            'answertype' : oca_extract(event, 'AnswerType'),
        }
        columns = list(row.keys())
        values = tuple(row.get(col) for col in columns)
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f"INSERT INTO oca_events_staging ({', '.join(columns)}) VALUES ({placeholders})"
        staging_execute(db, insert_sql, values)


def appearance_outcome_to_dict(elem):
    """Convert appearance outcome element to dictionary"""
    outcome_dict = {}
    
    outcome_type_elem = elem.find(oca_tag('AppearanceOutcomeType'))
    if outcome_type_elem is not None:
        outcome_dict['appearanceoutcometype'] = outcome_type_elem.text
    
    based_on_elem = elem.find(oca_tag('OutcomeBasedOnType'))
    if based_on_elem is not None:
        outcome_dict['outcomebasedontype'] = based_on_elem.text
    else:
        outcome_dict['outcomebasedontype'] = None
    
    return outcome_dict


def parse_appearances(case, db):
    """ for a case parse all the values for the oca_appearances
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """

    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # First, delete existing records for this case to handle multiple appearances
    staging_execute(db, "DELETE FROM oca_appearances_staging WHERE indexnumberid = ?", (IndexNumberId,))

    appearances = case.find(oca_tag('Appearances'))

    if appearances is None:
        return None

    for appearance in appearances.iter(oca_tag('Appearance')):

        appearance_outcomes = appearance.find(oca_tag('AppearanceOutcomes'))        

        if appearance_outcomes is not None:
            # Return as a list of dictionaries
            AppearanceOutcomes = [appearance_outcome_to_dict(i) for i in appearance_outcomes.iter(oca_tag('AppearanceOutcome'))]
        else:
            AppearanceOutcomes = []

        row = {
            'indexnumberid' : IndexNumberId,
            'appearancedatetime' : oca_extract(appearance, 'AppearanceDateTime'),
            'appearancepurpose' : oca_extract(appearance, 'AppearancePurpose'),
            'appearancereason' : oca_extract(appearance, 'AppearanceReason'),
            'appearancepart' : oca_extract(appearance, 'AppearancePart'),
            'motionsequence' : oca_extract(appearance, 'MotionSequence'),
            'appearanceoutcomes' : AppearanceOutcomes,
        }
        columns = list(row.keys())
        values = tuple(row.get(col) for col in columns)
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f"INSERT INTO oca_appearances_staging ({', '.join(columns)}) VALUES ({placeholders})"
        staging_execute(db, insert_sql, values)


def parse_motions(case, db):
    """ for a case parse all the values for the oca_motions
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """
    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # First, delete existing records for this case to handle multiple motions
    staging_execute(db, "DELETE FROM oca_motions_staging WHERE indexnumberid = ?", (IndexNumberId,))

    motions = case.find(oca_tag('Motions'))

    if motions is None:
        return None

    for motion in motions.iter(oca_tag('Motion')):
        row = {
            'indexnumberid' : IndexNumberId,
            'sequence' : oca_extract(motion, 'Sequence'),
            'motiontype' : oca_extract(motion, 'MotionType'),
            'primaryrelief' : oca_extract(motion, 'PrimaryRelief'),
            'fileddate' : oca_extract(motion, 'FiledDate'),
            'filingpartiesroles' : oca_extract_array2(motion, 'FilingParties', 'FilingParty', 'Role'),
            'motiondecision' : oca_extract(motion, 'MotionDecision'),
            'motiondecisiondate' : oca_extract(motion, 'MotionDecisionDate'),
        }
        columns = list(row.keys())
        values = tuple(row.get(col) for col in columns)
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f"INSERT INTO oca_motions_staging ({', '.join(columns)}) VALUES ({placeholders})"
        staging_execute(db, insert_sql, values)


def parse_decisions(case, db):
    """ for a case parse all the values for the oca_decisions
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """

    # TODO: Need to further parse the text of the "Highlight" field, 
    # though it's not clear what is a useful way to structure this.

    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # First, delete existing records for this case to handle multiple decisions
    staging_execute(db, "DELETE FROM oca_decisions_staging WHERE indexnumberid = ?", (IndexNumberId,))

    decisions = case.find(oca_tag('Decisions'))

    if decisions is None:
        return None

    for decision in decisions.iter(oca_tag('Decision')):
        row = {
            'indexnumberid' : IndexNumberId,
            'sequence' : oca_extract(decision, 'Sequence'),
            'resultof' : oca_extract(decision, 'ResultOf'),
            'highlight' : oca_extract(decision, 'HighlightNoPersonallyIdentifyingInfo'),
        }
        columns = list(row.keys())
        values = tuple(row.get(col) for col in columns)
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f"INSERT INTO oca_decisions_staging ({', '.join(columns)}) VALUES ({placeholders})"
        staging_execute(db, insert_sql, values)


def parse_judgments(case, db):
    """ for a case parse all the values for the oca_judgments
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """

    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # First, delete existing records for this case to handle multiple judgments
    staging_execute(db, "DELETE FROM oca_judgments_staging WHERE indexnumberid = ?", (IndexNumberId,))

    judgments = case.find(oca_tag('Judgments'))

    if judgments is None:
        return None

    for judgment in judgments.iter(oca_tag('Judgment')):
        row = {
            'indexnumberid' : IndexNumberId,
            'sequence' : oca_extract(judgment, 'Sequence'),
            'amendedfromjudgmentsequence' : oca_extract(judgment, 'AmendedFromJudgmentSequence'),
            'judgmenttype' : oca_extract(judgment, 'JudgmentType'),
            'fileddate' : oca_extract(judgment, 'FiledDate'),
            'entereddatetime' : oca_extract(judgment, 'EnteredDateTime'),
            'withpossession' : oca_extract(judgment, 'WithPossession'),
            'latestjudgmentstatus' : oca_extract(judgment, 'LatestJudgmentStatus'),
            'latestjudgmentstatusdate' : oca_extract(judgment, 'LatestJudgmentStatusDate'),
            'totaljudgmentamount' : oca_extract(judgment, 'TotalJudgmentAmount'),
            'creditorsroles' : oca_extract_array2(judgment, 'Creditors', 'Creditor', 'Role'),
            'debtorsroles' : oca_extract_array2(judgment, 'Debtors', 'Debtor', 'Role'),
        }
        columns = list(row.keys())
        values = tuple(row.get(col) for col in columns)
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f"INSERT INTO oca_judgments_staging ({', '.join(columns)}) VALUES ({placeholders})"
        staging_execute(db, insert_sql, values)


def parse_warrants(case, db):
    """ for a case parse all the values for the oca_warrants
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    """

    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text

    # First, delete existing records for this case to handle multiple warrants
    staging_execute(db, "DELETE FROM oca_warrants_staging WHERE indexnumberid = ?", (IndexNumberId,))

    judgments = case.find(oca_tag('Judgments'))

    if judgments is None:
        return None

    for judgment in judgments.iter(oca_tag('Judgment')):

        JudgmentSequence = oca_extract(judgment, 'Sequence')

        warrants = judgment.find(oca_tag('Warrants'))

        if warrants is None:
            continue

        for warrant in warrants.iter(oca_tag('Warrant')):
            row = {
                'indexnumberid' : IndexNumberId,
                'judgmentsequence' : JudgmentSequence,
                'sequence' : oca_extract(warrant, 'Sequence'),
                'createdreason' : oca_extract(warrant, 'CreatedReason'),
                'ordereddate' : oca_extract(warrant, 'OrderedDate'),
                'issuancetype' : oca_extract(warrant, 'IssuanceType'),
                'issuancestayeddate' : oca_extract(warrant, 'IssuanceStayedDate'),
                'issuancestayeddays' : oca_extract(warrant, 'IssuanceStayedDays'),
                'issueddate' : oca_extract(warrant, 'IssuedDate'),
                'executiontype' : oca_extract(warrant, 'ExecutionType'),
                'executionstayeddate' : oca_extract(warrant, 'ExecutionStayedDate'),
                'executionstayeddays' : oca_extract(warrant, 'ExecutionStayedDays'),
                'marshalrequestdate' : oca_extract(warrant, 'MarshalRequestDate'),
                'marshalrequestrevieweddate' : oca_extract(warrant, 'MarshalRequestReviewedDate'),
                'enforcementagency' : oca_extract(warrant, 'EnforcementAgency'),
                'enforcementofficerdocketnumber' : oca_extract(warrant, 'EnforcementOfficerDocketNumber'),
                'propertiesonwarrantcities' : oca_extract_array2(warrant, 'PropertiesOnWarrant', 'PropertyOnWarrant', 'City'),
                'propertiesonwarrantstates' : oca_extract_array2(warrant, 'PropertiesOnWarrant', 'PropertyOnWarrant', 'State'),
                'propertiesonwarrantpostalcodes' : oca_extract_array2(warrant, 'PropertiesOnWarrant', 'PropertyOnWarrant', 'PostalCode'),
                'amendeddate' : oca_extract(warrant, 'AmendedDate'),
                'vacateddate' : oca_extract(warrant, 'VacatedDate'),
                'adultprotectiveservicesnumber' : oca_extract(warrant, 'AdultProtectiveServicesNumber'),
                'returneddate' : oca_extract(warrant, 'ReturnedDate'),
                'returnedreason' : oca_extract(warrant, 'ReturnedReason'),
                'executiondate' : oca_extract(warrant, 'ExecutionDate'),
            }
            columns = list(row.keys())
            values = tuple(row.get(col) for col in columns)
            placeholders = ', '.join(['?' for _ in columns])
            insert_sql = f"INSERT INTO oca_warrants_staging ({', '.join(columns)}) VALUES ({placeholders})"
            staging_execute(db, insert_sql, values)


def update_metadata(case, db, extract_date):
    """ for a case update the metadata table with dates

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    :param extract_date: date of the XML data extract from OCA
    """

    IndexNumberId = case.find(INDEX_NUMBER_ID_TAG).text
    
    updatedate = extract_date if not is_case_to_delete(case) else None
    deletedate = extract_date if is_case_to_delete(case) else None
    
    row = {
        'indexnumberid': IndexNumberId,
        'initialdate': extract_date,
        'updatedate': updatedate,
        'deletedate': deletedate
    }
    
    columns = list(row.keys())
    values = tuple(row.get(col) for col in columns)
    placeholders = ', '.join(['?' for _ in columns])
    insert_sql = f"INSERT OR REPLACE INTO oca_metadata_staging ({', '.join(columns)}) VALUES ({placeholders})"
    staging_execute(db, insert_sql, values)


def parse_case(case, db, extract_date):
    """ Parse a single case

    :param case: an lxml.etree element for a case index
    :param db: a DuckDB object
    :param extract_date: date of extract
    """
    buffer = getattr(db, 'write_buffer', None)
    if buffer is not None:
        buffer.begin_case()

    update_metadata(case, db, extract_date)

    # If this case is flagged for removal, skip the parsing steps
    if is_case_to_delete(case):
        if buffer is not None:
            buffer.commit_case()
        return

    parse_index(case, db)
    parse_causes(case, db)
    parse_addresses(case, db)
    parse_parties(case, db)
    parse_events(case, db)
    parse_appearances(case, db)
    parse_motions(case, db)
    parse_decisions(case, db)
    parse_judgments(case, db)
    parse_warrants(case, db)

    if buffer is not None:
        buffer.commit_case()


def _worker_thread(case_queue, db_queue, extract_date, thread_id, stats: ParseFileResult):
    """Worker thread that processes cases from the queue"""
    while True:
        try:
            case = case_queue.get(timeout=1)
        except queue.Empty:
            continue

        try:
            if case is None:  # Sentinel value to stop thread
                break

            # Each thread needs its own database connection
            thread_db = db_queue.get()
            try:
                parse_case(case, thread_db, extract_date)
                stats.record_ok()
            except Exception as e:
                index_id = _index_number_id_from_case(case)
                if index_id:
                    logger.warning(
                        "Parse case failed thread=%s indexnumberid=%s: %s",
                        thread_id,
                        index_id,
                        e,
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        "Parse case failed thread=%s: %s",
                        thread_id,
                        e,
                        exc_info=True,
                    )
                buffer = getattr(thread_db, 'write_buffer', None)
                if buffer is not None:
                    buffer.discard_case()
                stats.record_failed(str(e))
            finally:
                # Clear the case copy from memory
                case.clear()
                db_queue.put(thread_db)  # Return db connection to pool
        finally:
            case_queue.task_done()


def parse_file(xml_file, staging_db, extract_date, num_threads=8, file_name=None):
    """
    Parse XML file with multiple threads

    :param xml_file: file-like object or path to XML file
    :param staging_db: DuckDB database object
    :param extract_date: date of extract
    :param num_threads: number of worker threads (increasing this doesn't speed up much, bottleneck is the database writes)
    :param file_name: basename for summary logging (optional)
    :return: ParseFileResult with per-zip counters
    """
    from .duckdb_database import DuckDB

    stats = ParseFileResult()
    case_queue = queue.Queue(maxsize=num_threads * 10)
    db_queue = queue.Queue()

    for _ in range(num_threads):
        thread_db = DuckDB(staging_db.dbname)
        attach_write_buffer(thread_db)
        db_queue.put(thread_db)
    
    # Start worker threads
    threads = []
    for i in range(num_threads):
        t = threading.Thread(
            target=_worker_thread,
            args=(case_queue, db_queue, extract_date, i, stats),
        )
        t.start()
        threads.append(t)
    
    # Parse XML and feed cases to queue
    context = etree.iterparse(xml_file, tag=oca_tag('Index'))
    
    for _, case in context:
        case_copy = etree.fromstring(etree.tostring(case))
        case_queue.put(case_copy)
        stats.record_seen()
        if stats.cases_seen % PARSE_PROGRESS_INTERVAL == 0:
            logger.info("Parsed %s cases", stats.cases_seen)

        # Clear the case element to free memory
        case.clear()
        while case.getprevious() is not None:
            del case.getparent()[0]
    
    # Signal threads to stop (workers flush remaining buffer on sentinel)
    for _ in range(num_threads):
        case_queue.put(None)

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Close thread database connections (final flush for any stragglers)
    while not db_queue.empty():
        thread_db = db_queue.get()
        flush_write_buffer(thread_db)
        thread_db.close()

    label = file_name or getattr(xml_file, 'name', None) or 'unknown'
    logger.info(
        "Parse zip summary file=%s seen=%d ok=%d failed=%d",
        label,
        stats.cases_seen,
        stats.cases_parsed_ok,
        stats.cases_failed,
    )
    return stats

