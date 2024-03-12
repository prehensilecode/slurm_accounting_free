#!/usr/bin/env python3
import sys
import os
import csv
from pathlib import Path
import subprocess
import delorean
import datetime
import calendar
import argparse

debug_p = False

def read_pis(pis_file):
    global debug_p

    if debug_p:
        print(f'DEBUG: read_pis()')

    pis_lastnames = []
    with open(pis_file, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if debug_p:
                print(f'DEBUG: row = {row}')

            if row['Active?']:
                if debug_p:
                    print(f'DEBUG: read_pis: Active? field is not empty')

                if int(row['Active?']) > 0:
                    lastname = row['Last Name'].lower()
                    if len(lastname.split()) > 1:
                        lastname = ''.join(lastname.split())

                    pis_lastnames.append(lastname)
            else:
                if debug_p:
                    print(f'DEBUG: read_pis: Active? field is EMPTY')
                    print(f'DEBUG: read_pis: len(pis_lastnames) = {len(pis_lastnames)}')

                return pis_lastnames

    if debug_p:
        print(f'DEBUG: read_pis: len(pis_lastnames) = {len(pis_lastnames)}')

    return pis_lastnames


def main():
    global debug_p

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Debugging output')
    parser.add_argument('-r', '--reports-prefix', default='/ifs/sysadmin/RCM',
                        help='Reports prefix directory')
    parser.add_argument('-w', '--when', default=None,
                        help='Date for reporting in format YYYY-MM')
    args = parser.parse_args()

    debug_p = args.debug

    if debug_p:
        print(f'DEBUG: args = {args}')

    # compute reporting period
    period_str = None
    if args.when:
        period_str = args.when
    else:
        today = delorean.Delorean()
        last_month = today - datetime.timedelta(days=(today.datetime.day+1))
        period_str = last_month.date.strftime('%Y-%m')

    year = int(period_str.split('-')[0])
    month = int(period_str.split('-')[1])
    last_day = datetime.datetime(year, month, calendar.monthrange(year, month)[1])

    dt = datetime.timedelta(days=1)
    date_period_end = last_day + dt

    # period end is 1st day of following month
    if debug_p:
        print(f'DEBUG: period_str = {period_str}')

    command_template = f'sreport -P cluster AccountUtilizationByUser Account={{}} Tree Start={year}-{month:02}-01 End={date_period_end.year}-{date_period_end.month:02}-01 -T billing -t Hours'

    if debug_p:
        print('DEBUG: command_template = ', command_template)

    reports_prefix_dir = Path(args.reports_prefix)

    if debug_p:
        reports_prefix_dir = Path('RCM')
        print(f'DEBUG: reports_prefix_dir = {reports_prefix_dir}')

    pis_lastnames = read_pis(reports_prefix_dir / 'myorg_pis.csv')

    reports_dir = reports_prefix_dir / period_str / 'sreport'

    if debug_p:
        print(f'DEBUG: reports_dir = {reports_dir}')

    if not reports_dir.exists():
        now = delorean.Delorean(timezone='US/Eastern')
        print(f'{now.datetime.strftime("%Y-%m-%d %H:%M:%S %Z")} - INFO: reports_dir does not exist; creating …')
        os.mkdir(reports_dir)

    if debug_p:
        print(f'DEBUG: main(): there are {len(pis_lastnames)} PIs')

    for pi in pis_lastnames:
        if debug_p:
            print(f'DEBUG: Generating report for {pi} ...')

        # EXAMPLE
        #   command = 'sreport cluster AccountUtilizationByUser Account={} Tree Start=2021-02-01 End=2021-02-28 -T billing'.format(pi).split(' ')
        command = command_template.format(pi).split(' ')

        if debug_p:
            print(f'DEBUG: Command: {command}')

        report_file = reports_dir / f'{pi}.txt'
        with open(report_file, 'w') as outfile:
            outfile.write(subprocess.run(command, check=True,
                          capture_output=True, text=True).stdout)


if __name__ == '__main__':
    main()

