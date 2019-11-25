from lxml import etree
# from .database import Database


def drop_case_rows(case, db):
    """ remove a single case from the database 

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """
    case_id = case.find(oca_tag('IndexNumberId')).text
    db.sql(f"DELETE FROM oca_index WHERE indexnumberid = '{case_id}';")

def is_case_to_delete(case):
    """ determine if a case should from the database

    :param case: an lxml.etree element for a case index
    :return: boolean
    """
    return case.find(oca_tag('Delete')) is not None

# when refering to XML tags we need to have the "namespace" included as well
def oca_tag(tag):
    """ add the necessary namespace to an xml tag

    :param tag: an xml tag string
    :return: string for tag with namespace
    """
    return '{http://www.example.org/LandlordTenantExtractSchema}' + tag

# if there is no element to find calling text method raises error
def oca_extract(elem, tag):
    """ find the first occurance of an xml tag and extract the

    :param elem: an lxml.etree element
    :param tag: an xml tag to find
    :return: string for node text
    """
    x = elem.find(oca_tag(tag))
    return None if x is None else x.text

# some attributes can have multiple values that we want to keep on in the same table/row,
# so we format these for insertion into postgres array. These are either 1 or 2 levels deep.

def oca_extract_array1(elem, parent_tag, child_tag):
    """ find the first node for given parent tag then extract the text 
    for all children matching the child tag as a postgres array string

    :param elem: an lxml.etree element
    :param parent_tag: an xml tag for the parent node
    :param child_tag: an xml tag for the children nodes
    :return: postgres array string (eg. {foo, bar}) or None
    """
    parent_elem = elem.find(oca_tag(parent_tag))

    if parent_elem is not None:
       return "{" + ','.join([ i.text for i in parent_elem.findall(oca_tag(child_tag)) ]) + "}"
    else:
        return None

def oca_extract_array2(elem, grandparent_tag, parent_tag, child_tag):
    """ find the first node for given gandparent tag then extract all 
    the parent nodes and for each parent node extract the text for its 
    child as a postgres array string

    :param elem: an lxml.etree element
    :param gandparent_tag: an xml tag for the grandparent node
    :param parent_tag: an xml tag for the parent nodes
    :param child_tag: an xml tag for the child node
    :return: postgres array string (eg. {foo, bar}) or None
    """
    grandparent_elem = elem.find(oca_tag(grandparent_tag))

    if grandparent_elem is not None:
       return '{' + ','.join([ i.find(oca_tag(child_tag)).text for i in grandparent_elem.findall(oca_tag(parent_tag)) ]) + '}'
    else:
        return None


def parse_index(case, db):
    """ for a case parse all the values for the oca_index 
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """
    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    row = [{
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
    }]

    db.insert_rows(row, 'oca_index')


def parse_causes(case, db):
    """ for a case parse all the values for the oca_causes
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """
    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    causes = case.find(oca_tag('PrimaryClaimCauseOfActions'))

    if causes is None:
        return None

    rows = []
    for cause in causes.iter(oca_tag('PrimaryClaimCauseOfAction')):
        rows.append({
            'indexnumberid' : IndexNumberId,
            'causeofactiontype' : oca_extract(cause, 'CauseOfActionType'),
            'interestfromdate' : oca_extract(cause, 'InterestFromDate'),
            'amount' : oca_extract(cause, 'Amount'),
        })

    if rows:
        db.insert_rows(rows, 'oca_causes')


def parse_addresses(case, db):
    """ for a case parse all the values for the oca_addresses
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """
    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    addresses = case.find(oca_tag('PropertyAddresses'))

    if addresses is None:
        return None

    rows = []
    for address in addresses.iter(oca_tag('PropertyAddress')):

        rows.append({
            'indexnumberid' : IndexNumberId,
            'city' : oca_extract(address, 'City'),
            'state' : oca_extract(address, 'State'),
            'postalcode' : oca_extract(address, 'PostalCode'),
        })
        
    if rows:
        db.insert_rows(rows, 'oca_addresses')

def parse_parties(case, db):
    """ for a case parse all the values for the oca_parties
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """
    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    parties = case.find(oca_tag('Parties'))

    if parties is None:
        return None

    rows = []
    for party in parties.iter(oca_tag('Party')):

        rows.append({
            'indexnumberid' : IndexNumberId,
            'role' : oca_extract(party, 'Role'),
            'partytype' : oca_extract(party, 'PartyType'),
            'representationtype' : oca_extract(party, 'RepresentationType'),
            'undertenant' : oca_extract(party, 'Undertenant'),
        })

    if rows:
        db.insert_rows(rows, 'oca_parties')


def parse_events(case, db):
    """ for a case parse all the values for the oca_events
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """
    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    events = case.find(oca_tag('Events'))

    if events is None:
        return None

    rows = []
    for event in events.iter(oca_tag('Event')):

        rows.append({
            'indexnumberid' : IndexNumberId,
            'eventname' : oca_extract(event, 'EventName'),
            'fileddate' : oca_extract(event, 'FiledDate'),
            'feetype' : oca_extract(event, 'FeeType'),
            'filingpartiesroles' : oca_extract_array2(event, 'FilingParties', 'FilingParty', 'Role'),
            'answertype' : oca_extract(event, 'AnswerType'),
        })

    if rows:
        db.insert_rows(rows, 'oca_events')


def appearance_outcome_to_json(elem):
    appearanceoutcometype_val = '"' + elem.find(oca_tag('AppearanceOutcomeType')).text + '"'
    outcomebasedontype_val = '"' + elem.find(oca_tag('OutcomeBasedOnType')).text + '"' if elem.find(oca_tag('OutcomeBasedOnType')) is not None else 'null'

    return f"{{\"appearanceoutcometype\":{appearanceoutcometype_val},\"outcomebasedontype\":{outcomebasedontype_val}}}"    

def parse_appearances(case, db):
    """ for a case parse all the values for the oca_appearances
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """

    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    appearances = case.find(oca_tag('Appearances'))

    if appearances is None:
        return None

    rows = []
    for appearance in appearances.iter(oca_tag('Appearance')):

        appearance_outcomes = appearance.find(oca_tag('AppearanceOutcomes'))        

        if appearance_outcomes is not None:
            AppearanceOutcomes = '[' + ','.join([ appearance_outcome_to_json(i) for i in appearance_outcomes.iter(oca_tag('AppearanceOutcome')) ]) + ']'
        else:
            AppearanceOutcomes = '[]'

        rows.append({
            'indexnumberid' : IndexNumberId,
            'appearancedatetime' : oca_extract(appearance, 'AppearanceDateTime'),
            'appearancepurpose' : oca_extract(appearance, 'AppearancePurpose'),
            'appearancereason' : oca_extract(appearance, 'AppearanceReason'),
            'appearancepart' : oca_extract(appearance, 'AppearancePart'),
            'motionsequence' : oca_extract(appearance, 'MotionSequence'),
            'appearanceoutcomes' : AppearanceOutcomes,
        })

    if rows:
        db.insert_rows(rows, 'oca_appearances')


def parse_motions(case, db):
    """ for a case parse all the values for the oca_motions
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """
    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    motions = case.find(oca_tag('Motions'))

    if motions is None:
        return None

    rows = []
    for motion in motions.iter(oca_tag('Motion')):

        rows.append({
            'indexnumberid' : IndexNumberId,
            'sequence' : oca_extract(motion, 'Sequence'),
            'motiontype' : oca_extract(motion, 'MotionType'),
            'primaryrelief' : oca_extract(motion, 'PrimaryRelief'),
            'fileddate' : oca_extract(motion, 'FiledDate'),
            'filingpartiesroles' : oca_extract_array2(motion, 'FilingParties', 'FilingParty', 'Role'),
            'motiondecision' : oca_extract(motion, 'MotionDecision'),
            'motiondecisiondate' : oca_extract(motion, 'MotionDecisionDate'),
        })

    if rows:
        db.insert_rows(rows, 'oca_motions')


def parse_decisions(case, db):
    """ for a case parse all the values for the oca_decisions
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """

    # TODO: Need to further parse the text of the "Highlight" field, 
    # though it's not clear what is a useful way to structure this.

    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    decisions = case.find(oca_tag('Decisions'))

    if decisions is None:
        return None

    rows = []
    for decision in decisions.iter(oca_tag('Decision')):
        rows.append({
            'indexnumberid' : IndexNumberId,
            'sequence' : oca_extract(decision, 'Sequence'),
            'resultof' : oca_extract(decision, 'ResultOf'),
            'highlight' : oca_extract(decision, 'HighlightNoPersonallyIdentifyingInfo'),
        })

    if rows:
        db.insert_rows(rows, 'oca_decisions')


def parse_judgments(case, db):
    """ for a case parse all the values for the oca_judgments
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """

    IndexNumberId = case.find(oca_tag('IndexNumberId')).text

    judgments = case.find(oca_tag('Judgments'))

    if judgments is None:
        return None

    rows = []
    for judgment in judgments.iter(oca_tag('Judgment')):

        rows.append({
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
        })

    if rows:
        db.insert_rows(rows, 'oca_judgments')


def parse_warrants(case, db):
    """ for a case parse all the values for the oca_warrants
    table and load the values into the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """

    IndexNumberId = case.find(oca_tag('IndexNumberId')).text


    judgments = case.find(oca_tag('Judgments'))

    if judgments is None:
        return None

    for judgment in judgments.iter(oca_tag('Judgment')):


        JudgmentSequence = oca_extract(judgment, 'Sequence')

        warrants = judgment.find(oca_tag('Warrants'))

        if warrants is None:
            return None

        rows = []
        for warrant in warrants.iter(oca_tag('Warrant')):

            rows.append({
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
            })

        if rows:
            db.insert_rows(rows, 'oca_warrants')

def parse_case(case, db):
    """ for a case, remove it from the database if it already exists, 
    then determine if it needs to be deleted permantly, if not then 
    parse all the values and insert the values into all the database table

    :param case: an lxml.etree element for a case index
    :param db: a Database object
    """

    # Remove the case from all tables if it already exists
    drop_case_rows(case, db)

    # If this case is flagged for removal, skip the parsing steps
    if not is_case_to_delete(case):
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
