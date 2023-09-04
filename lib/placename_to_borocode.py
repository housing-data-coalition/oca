import re

QN_PLACENAMES_ANY = ["QUEENS", "QUEEN", "QN"]
QN_PLACENAMES_FULL = [
    "QUEENS",
    "QUUENS",
    "QUEEN",
    "QUENS",
    "QU",
    "QN",
    "SPRINGFEILD GARDENS",
    "OAKLAND GARDENS",
    "GLENDALE",
    "CAMBRIA HTS",
    "WHITESTONE",
    "RIDGEWWOD",
    "ROCKAWAY BEACH",
    "FAR ROCAKWAY",
    "REGO APRK",
    "WOODHHAVEN",
    "ST. ALABANS",
    "FAR RCOCKAWAY",
    "RIGEWOOD",
    "JAMAMICA",
    "FAR ROCK",
    "ROCKAWAY",
    "SPRINGFIERLD GARDENS",
    "RIDGWOOD",
    "ARVERN",
    "ROCKAWAY BEAC",
    "JAMAICA",
    "JAIMACA",
    "SOUTH JAMAICA",
    "JAMAICA HILLS",
    "KEW GARDENS",
    "KEW GARDENS HILLS",
    "QUEENS VILLAGE",
    "HOLLIS",
    "ASTORIA",
    "OLD ASTORIA",
    "SAINT ALBANS",
    "ST. ALBANS",
    "ST ALBANS",
    "RIDGEWOOD",
    "SPRINGFIELD GARDENS",
    "SOUTH RICHMOND HILL",
    "RICHMOND HILL",
    "RICHMOND HILLS",
    "FAR ROCKAWAY",
    "CORONA",
    "NORTH CORONA",
    "WOODHAVEN",
    "LAURELTON",
    "FLUSHING",
    "EAST FLUSHING",
    "FLUSHING HEIGHTS",
    "LONG ISLAND CITY",
    "LONG IS CITY",
    r"L\.I\.C\.",
    r"L\.I\.C",
    r"L.\ I\. C\.",
    "LIC",
    "FOREST HILLS",
    "WHIETSTONE",
    "EAST ELMHURST",
    "ELMHURST",
    "SUNNYSIDE",
    "OZONE PARK",
    "SOUTH OZONE PARK",
    "REGO PARK",
    "ARVERNE",
    "ROSEDALE",
    "MURRAY HILL",
    "SPRINGFIELD GARDENS NORTH",
    "FRESH MEADOWS",
    "UTOPIA",
    "POMONOK",
    "BELLEROSE",
    "MIDDLE VILLAGE",
    "BAISLEY PARK",
    "MASPETH",
    "WOODSIDE",
    "QUEENSBORO HILL",
    "HILLCREST",
    "GLEN OAKS",
    "FLORAL PARK",
    "NEW HYDE PARK",
    "DOUGLAS MANOR",
    "DOUGLASTON",
    "LITTLE NECK",
    "BRIARWOOD",
    "JACKSON HEIGHTS",
    "AUBURNDALE",
    "SPRINGFIELD GARDENS SOUTH",
    "BROOKVILLE",
    "BAYSIDE",
    "BAYSIDE HILLS",
    r"FT\. TOTTEN",
    "BAY TERRACE",
    "CLEARVIEW",
    "COLLEGE POINT",
    "CAMBRIA HEIGHTS",
    "ROCKAWAY PARK",
    "HOWARD BEACH",
    "EMHURST",
    "ELMHHURST",
    "JAMAICA EST",
    "KEW GARDNENS",
    "AVVERNE",
    "JACKONS HEIGHTS",
    "QAMAICA",
    "LONG ISLAND CIT",
    "LLC",
    "CORONA HEIGHTS",
    "SPRIMGFIELD GARDENS",
    "SPRINGFIELD HOUSE",
    "FUSHING",
    "JAMAICA A",
    "SPRINGFIELD FARDENS",
    r"ST\. APBANS",
    "RIDEWOOD",
    "KEW GARENS",
    "FAR ROCKAAWAY",
    "OZONR PARK",
    "ROSENDALE",
    "FORSET HILLS",
    "RRIDGEWOOD",
    "SPRIDNGFIELD GARDENS",
    "MEADOWS",
    "FRESH MEDOWS",
    "FESH MEADOWS",
    "JACKSOBN HEIGHTS",
    "WHITE STONE",
    "OZONE PAKR",
    r"R\.P",
    "EAST ELMHRUST",
    "BRIOARWOOD",
    "SPRINFIELD GARDENS",
    "GLENSDALE",
    "FIOREST HILLS",
    "CAMBRIA HEIGHYS",
    "FAROCKAWAY",
    "JACKSON EIGHTS",
    "FOREST HILLSD",
    "KKEW GARDENS",
    "JACKSN HEIGHTS",
    "HOWARD BECH",
    "SPRINGFELD GARDEN",
    "OAKLAND",
    "KEW GADENS",
    "JAMAIMCA",
    "RIARWOOD",
    "SPRING FIELD GARDENS",
    "WOOODHAVEN",
    "LONG ISD CITY",
    "JACKSON HEIGTHS",
    "HILLIS",
    "OZOE PARK",
    "FAR RCOKAWAY",
    "ELMHURSR",
    "JAMAIAC",
    "GLEANDALE",
    "HOPWARD BEACH",
    "FAR ROXCKAWAY",
    "LERAK CITY",
    "FIREST HILLS",
    "MIDDLE VAILLAGE",
    "COLLEG POINT",
    "LAURERLTON",
    "LFEFRAK CITY",
    "BELLREOSE",
    "GESH MEADOWS",
    "KEQW GARDENS",
    "REGA PARK",
    "RIDGEWWOOD",
    "SAITN ALBANS",
    "SPRINGFIELD",
    "FAR ROCKWAY",
    "ROEDALE",
    "HOWARD",
    "SOUTH OZONE",
    "SPRINGFIELD GARDEN",
    r"ST\.ALBANS",
    "AVERNE",
    "QUEEENS",
    "SPRINGFIELDS GARDENS",
    "SPRINGFIELD GDNS",
    "JACKSON HGHTS.",
    "QUEESN VILLAGE",
    "HOWEL BEACH",
    "JACKSON HTS",
    "JAMACIA",
    "ARVENE",
    "WOODHAEN",
    "EE",
    "OCEAN BAY",
    "LEFRAK CITY",
    "SOUTH OZONE PK.",
    "SOUTH OZONE PK",
    "WOODHAVENN",
    r"J\. HTS",
    r"J\. HT S",
    "CAMBRIA HT",
    "SPRINGFEILD GDNS",
    "SPRINGFIELD GAREDENS",
    "JACKSON HGHTS",
    "BROAD CHANNEL",
    "ROCKAWAY PARKWAY",
    "WOODISDE",
    "ROCKAWAY BCH",
    "JAMICA",
    "ATORIA",
    "QUNS",
    "JAMAIACA",
    "FORST HILLS",
    "SOUTH ZONE PARK",
    "FFOREST HILLS",
    "ROSEDLAE",
    "ASTORA",
    "ELMONT",
    "ELM",
    "FOREST HILL",
    "CAMBRRIA HEIGHTS",
    "FAR ROCKAWAWY",
    "LAURLETON",
    "BELLROSE",
    "WHITSTONE",
    "SPRINTFIELD GARDENS",
    r"S\. O\. PK",
    "OZONE PK",
    "CAMBRIA",
    "QUENNS",
    "FRESH MEASOWS",
    "COLLEGE PT",
    "ELMHURTS",
    "ROCHDALE",
    "SOUTH OZNE PARK",
    r"S\. OZONE PK",
    r"S\.O\.P",
    "SOP",
    "JAVA",
    "FAR RORCKAWAY",
    "SPRINGVIELD GARDENS",
    "EDGEMERE",
    "RIDEGWOOD",
    "FLUSHIGN",
    "HOLLISWOOD",
    "ROCKAWAY PK",
    "REGO PK",
    "REGO PRK",
    "F USHING",
    "SPRINFIEDL GARDENS",
    "MIDDLE VIALLAGE",
    "WOODAHVEN",
    r"J\.H",
    "JH",
    "JAMAICA ESTATES",
    "RICHMODN HILL",
    "ASORIA",
    "JACKSON HEIHGTS",
    "HOEARD BEACH",
    "JAM",
    "ASTOTIA",
    "HWARD BEACH",
    "FR ROCKWAY",
    "ROCHDALE VILLAGE",
    "BROARWOOD",
    "RICHOND HILL",
    "CAMBERIA HEIGHTS",
    "SPRINGFIELD GARDENSS",
    "RICHMONG HILL",
    "MIDDLE VILAGE",
    "FAR ROCAKAWAY",
    "CAMBRIA HEIHGTS",
    "JAMIACA",
    "SPRINGFIELD GADENS",
    "HAMILTON BEACH",
    "GELN OAKS",
    "BRAIRWOOD",
    "HOWAD BEACH",
    "RIDEGEWOOD",
    "OZOEN PARK",
    "RAVENSWOOD",
    "FRESHMEADOWS",
    "FRSH MEADOWS",
    "CAMBRIA HIGHTS",
    "SOUTH OZONR PARK",
    "SAINTALBANS",
    "ALBANS",
    "FLUSHIG",
    "KEW GARDEN",
    "SPRINGFIELD GRDNS",
    r"S\.ZONE PARK",
    "BAYSWATER",
    "HOLLIS WOOD",
    "BELLE HARBOR",
    "GLENSALE",
    "KEW GRDNS HILLS",
    "FAR ROKCAWAY",
    "KEW GARDEN HILLS",
    "RICHMOND HILLL",
    "LONG ISL AND CITY",
    "ALEFRAK CITY",
    "LEFRK CITY",
    "LEFRASK CITY",
    "JACKSON HEIGHS",
    "KEW GARDEN HILL",
    "CORON",
    "WHTIESTONE",
    "LONGISLAND CITY",
    "OREST HILLS",
    "CARONA",
    "JACKOSN HEIGHTS",
    "ONG ISLAND CITY",
    "LUSHING",
    "ORONA",
    "SPRINGFIELD GARDNES",
    "FRESH MEASDOWS",
    "SPRINGFILED GARDENS",
    "FORET HILLS",
    "JACKSONHEIGHTS",
    "JACKSON HIEGHTS",
    "FRESH MEADOW",
    "QUUENS VILLAGE",
    "RIDGBEWOOD",
    "CORONSA",
    "JSCKSON HEIGHTS",
    "JAMAIC",
    "LONG ISLAND",
    "JAMIACA ESTATES",
    "CAMBRIA HIEHGTS",
    "GLENDLE",
    "JAMAICA ESTS",
    "ELHURST",
    "LEFRAK CIY",
    "ST.ABLANS",
    "FLSUHING",
    "LONG ISLANE CITY",
    "ASTIRUA",
    "FLUSHINHG",
    "LEFRAK CIT",
    "MIDDLE VILLAG",
    "SPRINGFIELD GDS",
    "ELMURST",
    "LAURETON",
    "EFRESH MEADOWS",
    "JACKSON HEIGHTYS",
    "ROCKAWAY POINT",
    "LONG ISLANCD CITY",
    "JAKCSON HEIGHTS",
    "ROCAKWAY BEACH",
    "MIDLLE VILLAGE",
    "QARVERNE",
    "LONG ISL CITY",
    "LAURETLON",
    "LOND ISLAND CITY",
    "RIDGEWOODQ",
    "FOREST HIILS",
    "FAR ROCKAWY",
    "COROMA",
    "ROSDEALE",
    "MIDDLE VILALGE",
    "COLLEGE PIINT",
    "JAQCKSON HEIGHTS",
    "SPRINGFIELD GARDENN",
    "CORNA",
    "BRIRWOOD",
    "AVENUEN",
    "WOOSHAVEN",
    "LAURLTON",
    "JACSON HEIGHTS",
    "HOWARD BEACHE",
    "ROCKAWALY",
    "LINDENWOOD",
    "RISHMOND HILL",
    "BELL HARBOR",
    "JAMAICA ESTATE",
    "RICHMOIND HILL",
    "SOUTH OZONE PARKR",
    "ELMHURT",
    "FLUSHIN",
    "FRESH EMADOWS",
    "FOWARD BEACH",
    "SPRINGFIELD FIELDS",
    "ROCKAWAY FRONT PKWY",
    "ARVEYNE",
    "LONG ISLAN CITY",
    "JAAMICA",
    "FLUSHINBG",
    "LEFRACK CITY",
    "FRESH MAEADOWS",
    "FRESH MWEADOWS",
    "LONG ISLAND CIRY",
    "AMAICA",
    "FOREST HILS",
    "FORESTHILLS",
    "JACLSON HEIGHTS",
    "RICHMOND HLL",
    "LMHURST",
    "ACKSON HEIGHTS",
    "STORIA",
    "WAKEFIELD",
    "WOODAHAVEN",
    "RICHMON HILL",
    "CAMBRIA HGTH",
    "JAKSON HEIGHTS",
    "FGRESH MEADOWS",
    "CAMBRIE HEIGHTS",
    "FLUHING",
    "GELNDALE",
    "FLUSHNG",
    "FLUSHIING",
    "RICHWOOD",
    "HOLLIS HILLS",
    "LEFRAK CITIY",
    "CAMBRIA HEIGTS",
    "RROCKAWAY",
    "BELLEROSE MANOR",
    "BRIAROWOOD",
    "JACKSON HGTS",
    "GTRESH MEADOWS",
    r"\.AMAICA HILLS",
    "AMAICA HILLS",
    "JACKSON HEIGTS",
    "SOUTH OZONE PARKWAY",
    "OZON PARK",
    "RIDGEWOOOD",
    "FAR ROCKAWAYS",
    "BRIAWOOD",
    "RECO PARK",
    "FRERSH MEADOWS",
    "KEW GRDENS",
    "LEFRAL CITY",
    "RICMOND HILL",
    "ROCKWAY PARK",
    "WOODBINE",
    "JANMAICA",
    "GLENNDALE",
    "RICHMON DHILL",
    "FAR ROCKAWA",
    "KEW GARDENS HILL",
    "ROCHMOND HILL",
    r"Q\. VILLAGE",
    "EFRAK CITY",
    "SPRINGFIELD GARDFENS",
    "SPRIGFIELD GARDENS",
    "LAFRAK CITY",
    "BRIARWOOS",
    "FAR ROCKAAY",
    "ADDISLEIGH PARK",
    "CHANNEL DRIVE",
    "ENTSHING",
    "KEW GAQRDENS",
    "LEFAK CITY",
    "R-WAY",
    "RICHMONF HILL",
    "ROCKAWAY PQARK",
    "CORONAA",
    "FAR ROCKAWAU",
    "FOREST",
]
SI_PLACENAMES_ANY = [r"STATEN\s*ISLAND", "RICHMOND", "SI"]
SI_PLACENAMES_FULL = [
    "STATEN ISLAND",
    "STATEN ISLAN",
    "STAEN ISLAND",
    "STATEN ISLANED",
    "STAETN ISLAND",
    "STATEN ISLANDL",
    "STATEN ISAND",
    "STETN ISLAND",
    "SATEN ISLAND",
    "STATENM ISLAND",
    "STATE ISLAND",
    "SATTEN ISLAND",
    "STATEN ISALND",
    "SATATEN ISLAND",
    "STATENN ISLAND",
    "S",
    "SI",
    "SO",
    "SU",
    "DI",
    r"S\.I\.",
    r"S\.I",
    "SIC",
    "SIK",
    "RICHMOND",
]
MN_PLACENAMES_ANY = ["MANHATTAN", r"NEW\s*YORK", "MN"]
MN_PLACENAMES_FULL = [
    "MANHATTAN",
    "MN",
    "NEW YORK",
    "N EWYORK",
    "NEWYORK",
    "NEW YOR",
    "NEW Y ORK",
    "HARLEM",
    r"N\.Y\.",
    r"N\.Y",
    "NY",
    "MARBLE HILL",
    "ROOSEVELT ISLAND",
    "NEW YORK CITY",
    "YORK",
    "INWOOD",
]
BX_PLACENAMES_ANY = ["BRONX", "BX"]
BX_PLACENAMES_FULL = [
    "THE BRONX",
    "BRONX",
    "BX",
    "BRONXD",
    "OROOKLYN",
    "BRONXB",
    "BRNOX",
    "BLONX",
    "BBRONX",
    "BRONXE",
    "ORONX",
    "PARKCHESTER",
    "STONX",
    "BROX",
    "BDONX",
    "ABONX",
    "BRPMX",
    "TRONX",
    "BRONC",
    "BFONX",
    "PRONX",
    "BHONX",
    "WRONX",
    "GRONX",
    "BRONXS",
    "ARONX",
    "BROND",
    "NX",
    "LONX",
    "FNX",
    "SONX",
    "FRONX",
    "BRCNX",
    "NRONX",
    "DONX",
    "HONX",
    "BONX",
    "CONX",
    "BNX",
    "ONX",
    "RIVERDALE",
    "CITY ISLAND",
    "BRNX",
    "BBONX",
    "RONX",
    "GONX",
    "X",
    "EONX",
    "ERONX",
]
BK_PLACENAMES_ANY = ["BROOKLYN", "KINGS", "BK"]
BK_PLACENAMES_FULL = [
    "BROOKLYN",
    "KINGS",
    "BK",
    "BROOKOLYN",
    "BKLYN",
    "BROOKKLYN",
    "RROOKLYN",
    "BROOKYLN",
    "BROOOKLYN",
    "BRQOKLYN",
    "LROOKLYN",
    "BROKLYN",
    "BOOKLYN",
    "BRROKLYN",
    "BROOKLYLN",
    "FROOKLYN",
    "AVEKLYN",
    "EOKLYN",
    "BROOLYN",
    "ROOKLYN",
    "BROOKLN",
    "EROOKLYN",
    "VENUELYN",
    "HROOKLYN",
    "TROOKLYN",
    "OMSOKLYN",
    "OKLYN",
    "FOKLYN",
    "VEOOKLYN",
    "QROOKLYN",
    "AOOKLYN",
    "AROOKLYN",
    "BRONXLYN",
    "FOOKLYN",
    "NROOKLYN",
    "LYN",
    "OOKLYN",
    "MOKLYN",
    "EOOKLYN",
    "BLOOKLYN",
    "OOKLN",
    "CYPRESS HILLS",
    "LOWOKLYN",
    "HNOOKLYN",
    "GGOOKLYN",
    "BTOOKLYN",
    "IOOKLYN",
    "DOOKLYN",
    "COOKLYN",
    "UROOKLYN",
    "GROOKLYN",
    "BROOKLY",
    "BROOKYN",
]


# Match one of the patterns to the full string exactly
QN_PLACENAMES_ANY = re.compile('^\\s*(?:' + '|'.join(QN_PLACENAMES_ANY) + ')\\s*$', re.IGNORECASE)
SI_PLACENAMES_ANY = re.compile('^\\s*(?:' + '|'.join(SI_PLACENAMES_ANY) + ')\\s*$', re.IGNORECASE)
MN_PLACENAMES_ANY = re.compile('^\\s*(?:' + '|'.join(MN_PLACENAMES_ANY) + ')\\s*$', re.IGNORECASE)
BX_PLACENAMES_ANY = re.compile('^\\s*(?:' + '|'.join(BX_PLACENAMES_ANY) + ')\\s*$', re.IGNORECASE)
BK_PLACENAMES_ANY = re.compile('^\\s*(?:' + '|'.join(BK_PLACENAMES_ANY) + ')\\s*$', re.IGNORECASE)

# Match one of the patterns anywhere in the string, with boundaries
QN_PLACENAMES_FULL = re.compile('(?:\\b' + '\\b|\\b'.join(QN_PLACENAMES_FULL) + '\\b)', re.IGNORECASE)
SI_PLACENAMES_FULL = re.compile('(?:\\b' + '\\b|\\b'.join(SI_PLACENAMES_FULL) + '\\b)', re.IGNORECASE)
MN_PLACENAMES_FULL = re.compile('(?:\\b' + '\\b|\\b'.join(MN_PLACENAMES_FULL) + '\\b)', re.IGNORECASE)
BX_PLACENAMES_FULL = re.compile('(?:\\b' + '\\b|\\b'.join(BX_PLACENAMES_FULL) + '\\b)', re.IGNORECASE)
BK_PLACENAMES_FULL = re.compile('(?:\\b' + '\\b|\\b'.join(BK_PLACENAMES_FULL) + '\\b)', re.IGNORECASE)


def placename_to_borocode(x):
    if re.search(SI_PLACENAMES_FULL, x) or re.search(SI_PLACENAMES_ANY, x):
        return 'Si'
    elif re.search(QN_PLACENAMES_FULL, x) or re.search(QN_PLACENAMES_ANY, x):
        return 'Qn'
    elif re.search(BK_PLACENAMES_FULL, x) or re.search(BK_PLACENAMES_ANY, x):
        return 'Bk'
    elif re.search(BX_PLACENAMES_FULL, x) or re.search(BX_PLACENAMES_ANY, x):
        return 'Bx'
    elif re.search(MN_PLACENAMES_FULL, x) or re.search(MN_PLACENAMES_ANY, x):
        return 'Mn'
    else:
        return ''