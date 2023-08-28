# this script is used to test the geocoder on the first few records of oca_addresses.csv 
# docker build . --build-arg MODE=2 --build-arg SFTP_HOST=sftp.[rest of the url]
# docker run -it -v ${PWD}:/app oca-app /bin/bash 
# > python geocode_test.py

from pathlib import Path
import os
import datetime

import multiprocessing
import functools

import pandas as pd
import numpy as np
from pandas.util import hash_pandas_object
import censusgeocode as cg


pub_dir = Path('./lib/data-public/')

input_csv = pub_dir / 'oca_addresses.csv'
output_csv = pub_dir / 'oca_addresses_test.csv'

# keep all cols
keep_cols = lambda x: x

df = pd.read_csv(
    input_csv, 
    dtype = str,
    index_col = False, 
    usecols=keep_cols,
    keep_default_na=False
)

# sub-select for all addresses that are missing latitude; needs to have a house number
records = df[(((pd.isna(df['lat'])) | (df['lat'] == '')) & (df['house_number'] != ''))].copy().reset_index()

print(f'Geocoding {len(records)} entries in {output_csv} using another geocoder.')

def geocode_using_census_batch(dataframe):

    # save a copy of the current columns
    cols = dataframe.columns
    processing = dataframe.copy()

    # create columns and a temp index to send off to censusgeocode
    processing['addr1'] = processing['house_number'] + ' ' + processing['street_name']
    processing['id'] = processing.index
    processing['null'] = None

    temp_file = pub_dir / f'temp_{hash_pandas_object(processing).values[0]}.csv'

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
    except:
        done['msg2'] = "Failed (unknown error with batch input)"
        return processing

print(datetime.datetime.now())
with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
    chunk_size = 2500 # census batch limit is 10,000. Smaller batches tend to work better
    data_split = np.split(records, range(chunk_size, records.shape[0], chunk_size))
    it = pd.concat(pool.map(geocode_using_census_batch, data_split))

# join back via IDs ...
pd.DataFrame(it).to_csv(output_csv, index=False)
print(datetime.datetime.now())

# 470748 entries in 6 minutes with processes at 2500 chunk size !!