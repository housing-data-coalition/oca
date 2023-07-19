# NYC Housing Court Filings

The [Housing Data Coalition](https://www.housingdatanyc.org/) (HDC) has received housing court filings data from the New York State Office of Court Administration (OCA). In this repository we manage the Extract-Transform-Load (ETL) process for getting raw XML filings data from OCA via SFTP, parsing the nested XML data into a set of tables, and making those CSV files publicly available for download.

To work with these data you can use the [NYCDB](https://github.com/nycdb/nycdb) to automatically load all of the tables into a PostgreSQL database for analysis. You can also find documentation about the data, including a [data dictionary](https://docs.google.com/spreadsheets/d/1GMDomQr8gEave6uLpLby9gQU0oMoGRL39kQdNbBJEqE) on the [NYCDB wiki](https://github.com/nycdb/nycdb/wiki/Dataset:-OCA-Housing-Court-Records).

When utilizing this work, please use one of the following attributions and links:

> Data from the New York State Office of Court Administration [via the Housing Data Coalition](https://github.com/housing-data-coalition/oca) in collaboration with the [Right to Counsel Coalition](https://www.righttocounselnyc.org/).

> Data from the New York State Office of Court Administration [via the Housing Data Coalition](https://github.com/housing-data-coalition/oca). This data has been obtained and made available through the collaborative efforts of the [Housing Data Coalition](https://www.housingdatanyc.org/), the [Right to Counsel Coalition](https://www.righttocounselnyc.org/), [BetaNYC](https://beta.nyc/), the [Association for Neighborhood and Housing Development](https://anhd.org/), the [University Neighborhood Housing Program](https://unhp.org), and [JustFix](https://www.justfix.org/).

## License 

This work is licensed under a [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License](http://creativecommons.org/licenses/by-nc-sa/4.0/). 

<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/"><img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by-nc-sa/4.0/88x31.png" /></a>

## CSV Files

[![Date Last Updated](https://oca-data.s3.amazonaws.com/public/last-updated-shield.png)](https://oca-data.s3.amazonaws.com/public/last-updated-date.txt)

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

The data we receive from OCA is an extract of all landlord and tenant cases in NYC housing court, without personally identifying information. For more details about the raw data and the final parsed tables, see [`/docs`](/docs).

## About the code

For information about the details of various components, see [`/lib`](/lib)

### Setup

First, you will only be able to run this yourself if you have HDC's credentials to access to the SFTP to get the raw data transfered from OCA and access to the private AWS S3 where those files are stored. 

You will need Docker and Docker Compose.

First, you'll want to create an `.env` file by copying the example one:

```
cp .env.example .env     # Or 'copy .env.example .env' on Windows
```

Take a look at the `.env` file and fill in the AWS S3 credentials.


To run the whole process in the docker container run:

```
docker-compose run app
```

### Modes

This ETL process has two modes: Level 1 and Level 2. Level 1 accesses the SFTP for general OCA usage and produces an `oca_addresses` CSV file with a column for zipcode. Level 2 accesses a more restrictive SFTP and produces an `oca_addresses` CSV file with the building address columns (address without apartment or unit number) and an additional `oca_addresses_with_bbl` CSV file that only displays rows and data if the Borough-Block-Lot (BBL) or tax lot has 10 or more units. To switch between modes, edit the `MODE` variable in the .env file.

Mode 1 can run on both SFTP Level 1 and Level 2, but Mode 2 can only run on the Level 2 SFTP. Additional security measures need to be put in place for the database, the `oca_addresses` table, and the CSV of the Level 2 data.

Mode 2 adds PLUTO as an additional dataset and installs the matching version of [GeoSupport](https://www.nyc.gov/site/planning/data-maps/open-data/dwn-gde-home.page).

You need to re-run `docker-compose build` when switching modes. To see echo outputs in your terminal for debugging, run `docker-compose build --progress=plain`.

### (Optional) RDS Clone

If you have an existing database on Amazon, you can use S3 to "clone" the CSV files to the RDS service (or you can do a sql.dump). To enable add  the RDS database uri to the `CLONED_DATABASE_URL` variable in the .env file. After the main process is done, additional scripts will overwrite the contents on the RDS. Make sure there are proper permissions for the RDS to connect to S3 (if there is a bucket policy).

```json
{
    "Version": "2012-10-17",
    "Id": "Policy1234",
    "Statement": [
        {
            "Sid": "Stmt1623892536589",
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::..."
            },
            "Action": "s3:*",
            "Resource": "arn:aws:s3:::..."
        }
    ]
}
```