# NYC Housing Court Filings

The [Housing Data Coalition](https://www.housingdatanyc.org/) (HDC) has received NYC housing court filings data from the New York State Office of Court Administration (OCA). In this repository we manage the ETL process of getting raw XML filings data, parsing the XML into a set of tables, and making those CSV files public.

To work with these data you can use the [`nycdb_oca`](https://github.com/austensen/nycdb_oca) plugin for [NYCDB](https://github.com/nycdb/nycdb).


#### TODO

* We still need to get the SFTP credentials from OCA. Once we do, then we'll need to add a step that moves the file from the SFTP to the private S3 bucket.
* We still need to learn how frequently the incremental extracts will be made available on the SFTP. Then we'll need to schedule this job to run automatically. 
* We need to add a feature to get all the XML files in the S3 and iterate over them in order for parsing. 

## CSV Files

* [`oca_index`](https://s3.amazonaws.com/oca-data/public/oca_index.csv)
* [`oca_causes`](https://s3.amazonaws.com/oca-data/public/oca_causes.csv)
* [`oca_addresses`](https://s3.amazonaws.com/oca-data/public/oca_addresses.csv)
* [`oca_parties`](https://s3.amazonaws.com/oca-data/public/oca_parties.csv)
* [`oca_events`](https://s3.amazonaws.com/oca-data/public/oca_events.csv)
* [`oca_appearances`](https://s3.amazonaws.com/oca-data/public/oca_appearances.csv)
* [`oca_appearance_outcomes`](https://s3.amazonaws.com/oca-data/public/oca_appearance_outcomes.csv)
* [`oca_motions`](https://s3.amazonaws.com/oca-data/public/oca_motions.csv)
* [`oca_decisions`](https://s3.amazonaws.com/oca-data/public/oca_decisions.csv)
* [`oca_judgments`](https://s3.amazonaws.com/oca-data/public/oca_judgments.csv)
* [`oca_warrants`](https://s3.amazonaws.com/oca-data/public/oca_warrants.csv)


## About the data

The data we receive from OCA is an extract of all landlord and tenant cases in NYC housing court, without personally identifying information. For more details see [`/docs`](/docs).

...

## Setup

First, you will only be able to run this yourself if you have HDC's credentials to access to the SFTP to get the raw data transfered from OCA and access to the private AWS S3 where those files are stored. 

You will need Docker.

First, you'll want to create an `.env` file by copying the example one:

```
cp .env.example .env     # Or 'copy .env.example .env' on Windows
```

Take a look at the `.env` file and fill in the AWS S3 credentials.


To run the whole process in the docker container run:

```
docker-compose run app
```

## How it works

...


