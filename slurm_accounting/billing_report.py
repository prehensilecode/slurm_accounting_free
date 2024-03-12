#!/usr/bin/env python3
import sys
import os
import argparse
import calendar
import delorean
import datetime
import subprocess
from decimal import Decimal

debug_p = False

def print_report(account, year, month, sreport):
    global debug_p

    # total usage for account
    total_billing_tre = Decimal(sreport.strip().split('\n')[0].split('|')[5])

    rate = Decimal('0.0123')
    penny = Decimal('0.01')
    cluster = os.getenv('CMD_WLM_CLUSTER_NAME')

    period = datetime.datetime(year=year, month=month, day=1)

    print(f'USAGE REPORT FOR {account} ON CLUSTER {cluster} - {period.strftime("%B %Y")}')
    print(f'Rate = $ {rate} per SU')
    print('')

    total_su = total_billing_tre
    print(f'Compute usage: {float(total_su):>8.6e} SU')
    charge = total_su * rate
    print(f'Charge: $ {charge.quantize(penny):,}')
    print('')
    print('')

    # per user usage for account
    print('    Per-user usage and charge')
    print(f'    {"Name":<20} {"User ID":>12} {"Usage (SU)":>14} {"Charge":>14}')
    per_user_billing_tres = sreport.strip().split('\n')[1:]
    for item in per_user_billing_tres:
        login = item.split('|')[2]
        name = item.split('|')[3]
        su = Decimal(item.split('|')[5])
        charge = su * rate
        print(f'    {name:<20} {login:>12} {su:>14.6e}     ${charge.quantize(penny):>9,}')


def main():
    global debug_p
    global rate

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Debugging output')
    parser.add_argument('-w', '--when', default=None,
                        help='Period for reporting in format YYYY-MM. Default: current month.')
    parser.add_argument('-a', '--account', required=True,
                        help='Account/Project for which to generate report (something like "xxxxxPrj")')
    args = parser.parse_args()

    debug_p = args.debug

    # compute reporting period
    period_str = None
    if args.when:
        period_str = args.when
    else:
        today = delorean.Delorean()
        period_str = today.date.strftime('%Y-%m')

    year = int(period_str.split('-')[0])
    month = int(period_str.split('-')[1])

    year = int(period_str.split('-')[0])
    month = int(period_str.split('-')[1])
    req_date = delorean.parse(f'{year}-{month:02d}-01 00:00:00')
    last_day = datetime.datetime(year, month, calendar.monthrange(year, month)[1])
    dt = datetime.timedelta(days=1)
    date_period_end = last_day + dt

    # date when cluster started recording accounting data
    earliest = delorean.parse('2021-02-01 00:00:00')

    if req_date < earliest:
        print(f'ERROR: billing_report: no usage accounting data before Feb 01, 2021')
        sys.exit(1)

    command_template = f'sreport -n -P cluster AccountUtilizationByUser Account={{}} Tree Start={year}-{month:02}-01 End={date_period_end.year}-{date_period_end.month:02}-01 -T billing -t hours'

    command = command_template.format(args.account).split(' ')
    sreport = subprocess.run(command, check=True, capture_output=True, text=True).stdout

    if sreport:
        print_report(args.account, year, month, sreport)
    else:
        # empty report
        period = datetime.datetime(year=year, month=month, day=1)
        print(f'billing_report: no usage accounting data for {period.strftime("%B %Y")}')
        sys.exit(0)


if __name__ == '__main__':
    main()
