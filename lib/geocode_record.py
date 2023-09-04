import os
import pandas as pd
from pandas.util import hash_pandas_object

from geosupport import Geosupport,GeosupportError
import usaddress
import censusgeocode as cg

from .placename_to_borocode import placename_to_borocode

# initialize geosupport
g = Geosupport()

def parse_address(addr):
    """parses full address string and returns dict of address components needed for geocoding

    Args:
        addr (str): full street address

    Returns:
        dict: dict of strings for house_number, street_name, borough_code, and place_name
    """
    try:
        tags, _ = usaddress.tag(addr)
        # GRAND CONCOURSE fix? https://github.com/datamade/usaddress/issues/197
        if 'grand concourse' in addr.lower():
            tags, _ = usaddress.tag(addr + ', NY')

        house_number = ' '.join([v for k, v in tags.items() if k.startswith('AddressNumber')])
        street_name = ' '.join([v for k, v in tags.items() if k.startswith('StreetName')])
    except usaddress.RepeatedLabelError as e :
        tags = e.parsed_string
        house_number = ' '.join([x[0] for x in tags if x[1].startswith('AddressNumber')])
        street_name = ' '.join([x[0] for x in tags if x[1].startswith('StreetName')])

    return dict(
        house_number = house_number,
        street_name = street_name
    )

def parse_output(geo):
    """parse out desired variables from geosupport return dict

    Args:
        geo (dict): return from geosupport functions

    Returns:
        dict: dict of strings for various geocode results, including official values for inputs, lat/lon, admin codes for building and areas, return codes and messages to diagnose unsuccessful geocode attempts
    """
    return dict(
        # Normalized address: 
        sname = geo.get('First Street Name Normalized', ''),
        hnum = geo.get('House Number - Display Format', ''),
        boro = geo.get('First Borough Name', ''),
        
        # longitude and latitude of lot center
        # if address out of range (GRC 42), 
        # the following would be empty
        lat = geo.get('Latitude', ''),
        lon = geo.get('Longitude', ''),
        
        # Some sample administrative areas: 
        # for all the available fields check out 
        # http://api-geosupport.planninglabs.nyc:5000/1b/?house_number=120&street_name=broadway&borough=mn
        bin = geo.get('Building Identification Number (BIN) of Input Address or NAP',''),
        bbl = geo.get('BOROUGH BLOCK LOT (BBL)', {}).get('BOROUGH BLOCK LOT (BBL)', '',),
        cd = geo.get('COMMUNITY DISTRICT', {}).get('COMMUNITY DISTRICT', ''),
        ct = geo.get('2010 Census Tract', ''),
        council = geo.get('City Council District', ''), 

        # the return codes and messaged are for diagnostic puposes
        # highly recommend to include in the final output
        # to look up what the return codes mean, check out below: 
        # https://nycplanning.github.io/Geosupport-UPG/chapters/chapterII/section02/
        grc = geo.get('Geosupport Return Code (GRC)', ''),
        grc2 = geo.get('Geosupport Return Code 2 (GRC 2)', ''),
        msg = geo.get('Message', 'msg err'),
        msg2 = geo.get('Message 2', 'msg2 err'),
    )


def geocode_record(input, addr_cols):
    """geocode the address from a data record using Geosupport. It parses out address components using `usadress` and the geocodes it using NYC DCP's Geosupport

    Args:
        input (dict): a record of data (eg. from pandas `DataFrame.to_dict('records')`)
        addr_col (str): name of the field in the record that has the full address to geocode

    Returns:
        dict: the same record of data from `input` with the geocode results added
    """    
    try: 
        addr = ', '.join([input[col] for col in addr_cols if input[col].strip()])
        addr_args = parse_address(addr)
        addr_args['zip_code'] = input['postalcode']
        geo = g.address(**addr_args)
        ret = input
        ret.update(dict(status = 'success'))
        ret.update(addr_args)
        ret.update(parse_output(geo))
        return ret
    except GeosupportError as e:
        geo = e.result
        ret = input
        ret.update(dict(status = 'error'))
        ret.update(addr_args)
        ret.update(parse_output(geo))
        return ret

def geocode_using_census_batch(dataframe, pub_dir):

    # save a copy of the current columns
    cols = dataframe.columns
    processing = dataframe.copy()

    # create columns and a temp index to send off to censusgeocode
    processing['addr1'] = processing['house_number'] + ' ' + processing['street_name']
    processing['id'] = processing.index
    processing['null'] = None

    temp_file = os.path.join(pub_dir, f'temp_{hash_pandas_object(processing).values[0]}.csv')

    try:
        # unique id, street address, state, city, zip code
        processing[['id','addr1','null','null','postalcode']].to_csv(temp_file, index = False, header= False)
        done = pd.DataFrame(cg.addressbatch(str(temp_file), returntype='locations'))
        done['id'] = done['id'].astype(int)

        # delete file
        os.remove(temp_file)

        # overwrite some columns
        done['status'] = done['match'].astype(str)
        done['msg2'] = done['matchtype'].astype(str)

        return done[['id','status','msg2','lat','lon']].merge(processing, on = 'id', suffixes=('','_x'))[cols]
    except Exception as error:
        print('Error with geocoding:', error)
        processing['msg2'] = "Failed (un-logged error with batch geocoding)"
        return processing[cols]