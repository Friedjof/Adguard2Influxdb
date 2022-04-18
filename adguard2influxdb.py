# Friedjof Noweck
# 2022-04-17 So
# Quellen:
# https://github.com/frenck/python-adguardhome
# https://github.com/karrot-dev/fritzinfluxdb

"""Asynchronous Python client for the AdGuard Home API."""
import os
import asyncio

from datetime import datetime
import configparser
import logging
import time

from adguardhome import AdGuardHome
from influxdb import InfluxDBClient
        

def check_db_status(db_handler: InfluxDBClient, db_name: str) -> None:
    """
    Check if InfluxDB handler has access to a database.
    If it doesn't exist try to create it.
    Parameters
    ----------
    db_handler: influxdb.InfluxDBClient
        InfluxDB handler object
    db_name: str
        Name of DB to check
    """

    try:
        dblist = db_handler.get_list_database()
    except Exception as e:
        logging.error('Problem connecting to database: %s', str(e))
        return

    if db_name not in [db['name'] for db in dblist]:

        logging.warning(f'Database <{db_name}> not found, trying to create it')

        try:
            db_handler.create_database(db_name)
        except Exception as e:
            logging.error('Problem creating database: %s', str(e))
            return
    else:
        logging.debug(f'Influx Database <{db_name}> exists')

    logging.info("Connection to InfluxDB established and database present")


def read_config(filename: str) -> configparser:
    """
    Read config ini file and return configparser object
    Parameters
    ----------
    filename: str
        path of ini file to parse
    Returns
    -------
    configparser.ConfigParser(): configparser object
    """

    logging.info("Read configuration...")
    config = None

    # check if config file exists
    if not os.path.isfile(filename):
        logging.error(f'Config file "{filename}" not found')
        exit(1)

    # check if config file is readable
    if not os.access(filename, os.R_OK):
        logging.error(f'Config file "{filename}" not readable')
        exit(1)

    try:
        config = configparser.ConfigParser()
        config.read(filename)
    except configparser.Error as e:
        logging.error("Config Error: %s", str(e))
        exit(1)

    logging.info("...Done parsing config file")

    return config


def sanitize_adguard_return_data(results: dict) -> dict:
    """
    Sometimes integers are returned as string
    try to sanitize this a bit
    Parameters
    ----------
    results: dict
        dict of results from adguard connection call
    Returns
    -------
    dict: sanitized version of results
    """

    return_results = {}
    for instance in results:
        # turn None => 0
        if results[instance] is None:
            return_results.update({instance: 0})
        else:
            # try to parse as int
            try:
                return_results.update({instance: float(results[instance])})
            # keep it a string if this fails
            except ValueError:
                return_results.update({instance: results[instance]})

    return return_results


def write2influxdb(influxdb_client: InfluxDBClient, configuration: configparser, data: dict) -> None:
    json: dict = {
        "measurement": configuration.get("influxdb", "measurement_name"),
        "time": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        "fields": sanitize_adguard_return_data(results=data)
    }

    try:
        influxdb_client.write_points([json], time_precision="ms")
    except Exception as e:
        logging.error("Failed to write to InfluxDB <%s>: %s" % (configuration.get('influxdb', 'host'), str(e)))

    logging.info("...done")


async def main():
    """Show example on stats from your AdGuard Home instance."""
    values: dict = {}

    try:
        while True:
            configuration: configparser = read_config(
                filename=os.path.join(
                    os.path.dirname(__file__),
                    "configuration.ini"
                )
            )

            logging.debug("connection to InfluxDB...")

            influxdb: InfluxDBClient = InfluxDBClient(
                host=configuration.get("influxdb", "host"),
                username=configuration.get("influxdb", "username"),
                password=configuration.get("influxdb", "password"),
                port=configuration.getint(
                    "influxdb", "port", fallback=8086
                ),
                ssl=configuration.getboolean(
                    "influxdb", "ssl", fallback=False
                ),
                verify_ssl=configuration.getboolean(
                    "influxdb", "verify_ssl", fallback=False
                ),
                database=configuration.get("influxdb", "database")
            )
            logging.info("...done")

            check_db_status(influxdb, configuration.get("influxdb", "database"))

            async with AdGuardHome(
                    host=configuration.get("adguard", "host"),
                    port=configuration.getint("adguard", "port"),
                    tls=configuration.getboolean("adguard", "tls"),
                    username=configuration.get("adguard", "username"),
                    password=configuration.get("adguard", "password")
            ) as adguard:
                version = await adguard.version()
                values["version"] = version
                logging.info(f"AdGuard version: {version}")

                period = await adguard.stats.period()
                values["period"] = period
                logging.info(f"Stats period: {period}")

                result = await adguard.stats.avg_processing_time()
                values["avg_processing_time"] = result
                logging.info(f"Average processing time per query in ms: {result}")

                result = await adguard.stats.dns_queries()
                values["dns queries"] = result
                logging.info(f"DNS_queries: {result}")

                result = await adguard.stats.blocked_filtering()
                values["blocked_filtering"] = result
                logging.info(f"Blocked DNS queries: {result}")

                result = await adguard.stats.blocked_percentage()
                values["blocked_percentage"] = result
                logging.info(f"Blocked DNS queries ratio: {result}")

                result = await adguard.stats.replaced_safebrowsing()
                values["replaced_safebrowsing"] = result
                logging.info(f"Pages blocked by safe browsing: {result}")

                result = await adguard.stats.replaced_parental()
                values["replaced_parental"] = result
                logging.info(f"Pages blocked by parental control: {result}")

                result = await adguard.stats.replaced_safesearch()
                values["replaced_safesearch"] = result
                logging.info(f"Number of enforced safe searches: {result}")

                result = await adguard.filtering.rules_count(allowlist=False)
                values["rules_count"] = result
                logging.info(f"Total number of active rules: {result}")

                logging.info("Write this Date to the InfluxDB...")
                write2influxdb(influxdb_client=influxdb, configuration=configuration, data=values)

                logging.info("Clone Adguard connection.")

            logging.info("Close InfluxDB connection.")
            influxdb.close()

            logging.info("Wait configured interval.")
            time.sleep(configuration.getint("adguard", "interval", fallback=0))

    except KeyboardInterrupt:
        logging.info("Termination...")
        exit(0)


if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s - %(name)s - '
               '%(levelname)s - %(message)s',
        level=logging.INFO
    )

    logging.debug("Start loop")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        main()
    )
