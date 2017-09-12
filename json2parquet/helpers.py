# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
import re

import pyarrow as pa

logger = logging.getLogger("json2parquet")


def get_schema_from_redshift(redshift_schema, redshift_table, redshift_uri):
    """
    Creates a PyArrow Schema based on a Redshift Table, uses psycopg2
    """
    query = _get_redshift_schema(redshift_schema, redshift_table)
    raw_schema, _ = run_redshift_query(query, redshift_uri)
    return _convert_schema(raw_schema)


def _convert_schema(redshift_schema):
    fields = []
    for column in redshift_schema:
        column_name = column[0]
        column_type = column[1]
        # Need a way to pull out timestmap info, decimal precision
        if "(" in column_type:
            # Parsing types like Varying Character (200)
            result = re.search(r'(?P<type>[^\(\)]+)\((?P<size>\d+)\)', column_type)
            column_type = result.groupdict()['type']
        converted_type = REDSHIFT_TO_PYARROW_MAPPING[column_type.upper()]
        fields.append(pa.field(column_name, converted_type()))
    schema = pa.schema(fields)
    return schema



def run_redshift_query(query, redshift_uri, isolation_level=1):
    import psycopg2
    logger.debug("Running query:\n{}".format(query))
    uri = urlparse(redshift_uri)
    with psycopg2.connect(
        dbname=uri.path.strip('/'),
        user=uri.username,
        password=uri.password,
        host=uri.hostname,
        port=uri.port,
    ) as conn:
        conn.set_isolation_level(isolation_level)
        with conn.cursor() as cursor:
            cursor.execute(query)
            result = None
            error = None
            try:
                result = cursor.fetchall()
            except psycopg2.ProgrammingError as e:
                error = e
            except psycopg2.OperationalError as e:
                error = e
            except psycopg2.InternalError as e:
                error = e
            finally:
                cursor.close()
            return result, error


def _get_redshift_schema(table_name, schema_name):
    """
    Gets the table schema for any redshift table, Spectrum or Regular.
    Slower perf than using pg_table_def, but gets Spectrum tables
    """
    SCHEMA_QUERY = cleandoc("""
        SELECT column_name, data_type
        FROM svv_columns
        WHERE table_schema = '{schema_name}'
        AND table_name = '{table_name}'
        ORDER BY column_name;
    """.format(table_name=table_name, schema_name=schema_name))
    return SCHEMA_QUERY


# https://docs.aws.amazon.com/redshift/latest/dg/c_Supported_data_types.html
REDSHIFT_TO_PYARROW_MAPPING = {
    # Signed 2-byte Int
    "SMALLINT": pa.int16,
    "INT2": pa.int16,

    # Signed 4-byte Integer
    "INTEGER": pa.int32,
    "INT": pa.int32,
    "INT4": pa.int32,

    # Signed 8-byte Integer
    "BIGINT": pa.int64,
    "INT8": pa.int64,

    # Logical Boolean
    "BOOLEAN": pa.uint8,
    "BOOL": pa.uint8,

    # Single Precision Floating Point Numb
    "REAL": pa.float32,
    "FLOAT4": pa.float32,

    # Double  Precision Floating Point Numb
    "DOUBLE PRECISION": pa.float64,
    "FLOAT8": pa.float64,
    "FLOAT": pa.float64,

    # Exact numeric of selectable precision
    "DECIMAL": pa.decimal,
    "NUMERIC": pa.decimal,

    # Fixed Length String
    # PyArrow has no concept of fixed length strings in schemas
    "CHAR": pa.string,
    "CHARACTER": pa.string,
    "NCHAR": pa.string,
    "BPCHAR": pa.string,

    # Variable Length String
    "VARCHAR": pa.string,
    "CHARACTER VARYING": pa.string,
    "NVARCHAR": pa.string,
    "TEXT": pa.string,

    # Calender Date Y, M, D
    # Unsure if this should be date64 or date32
    # Redshift might ingest it as a string
    "DATE": pa.date64,

    # Timestamp w/o TZ info
    "TIMESTAMP": pa.timestamp,
    "TIMESTAMP WITHOUT TIME ZONE": pa.timestamp,

    # Timestamp with TZ
    # Need a way to pull TZ info
    "TIMESTAMPTZ": pa.timestamp,
    "TIMESTAMP WITH TIME ZONE": pa.timestamp,
}
